"""Size a change-scoped selection against the suite's duration profile.

One sizing answers two questions from the same profile: how many shards a
selection earns, and whether it should run at all. A selection earns one
shard per MIN_SHARD_PROFILE_SECONDS of profiled time, up to SHARD_COUNT;
missing timings underestimate work, never coverage. A selection that full
CI answers as fast is not run: selection_estimate names the reason, and the
dispatcher (before dispatch) and the selection workflow's plan job (before
any shard starts) both read it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from yoke_core.tools.ci_shards import DURATIONS_PATH, SHARD_COUNT

# Profiled test seconds one shard is worth carrying, deliberately well under
# the ~150s a shard's fixed runner setup costs. Profiled seconds are a floor:
# `profiled_size` sees only tests the committed profile already holds, and the
# tests a change adds are exactly the ones no full-suite run has measured yet,
# so a change-scoped selection always profiles at less than it runs. Budgeting
# at the break-even would assume that gap away. Erring low is also the cheaper
# side to be wrong on — one shard too many costs that runner's fixed setup
# beside work that was going to run anyway, one too few costs the selection
# the wall time it could have split.
MIN_SHARD_PROFILE_SECONDS = 60.0

# A selection at or above this share of the suite's profiled seconds is full
# CI's work: it saves too little runner time to be worth a second run beside
# the full suite every pull request already gets.
FULL_CI_SHARE = 0.70


def normalize_profile_target(root: Path, target: str) -> str | None:
    """Repo-relative profile spelling for *target*, or None if outside *root*.

    The committed profile keys are repo-relative node ids. Equivalent
    ``./relative``, in-checkout absolute, node-id, ``.`` and checkout-root
    spellings must therefore collapse to the same path before matching.
    A target that resolves outside *root* is dropped so it cannot silently
    match unrelated profile data.
    """
    root = root.resolve()
    path_text, sep, node = target.partition("::")
    suffix = f"::{node}" if sep else ""
    text = path_text.strip()
    if not text or text == ".":
        return f".{suffix}" if suffix else "."
    relative = text[2:] if text.startswith("./") else text
    while relative.startswith("./"):
        relative = relative[2:]
    if not relative or relative == ".":
        candidate = root
    else:
        candidate = (
            Path(relative) if Path(relative).is_absolute() else (root / relative)
        )
    try:
        rel = candidate.resolve().relative_to(root)
    except ValueError:
        return None
    rel_text = rel.as_posix()
    if rel_text == ".":
        return f".{suffix}" if suffix else "."
    return rel_text + suffix


def profiled_size(root: Path, targets: Sequence[str]) -> tuple[float, int]:
    """Profiled seconds and profiled test count for *targets*.

    Node ids in the committed profile are repo-relative, so a selected file,
    a directory, and a single node id all match by prefix. Tests the profile
    has never seen are invisible here, which makes this a floor: an
    underestimate costs a shard, never coverage.
    """
    try:
        durations = json.loads((root / DURATIONS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0, 0
    normalized = [
        spelling
        for target in targets
        if (spelling := normalize_profile_target(root, target)) is not None
    ]
    if any(spelling == "." or spelling.startswith(".::") for spelling in normalized):
        return sum(float(duration) for duration in durations.values()), len(durations)
    files = {target for target in normalized if target.endswith(".py")}
    others = tuple(
        target.rstrip("/") for target in normalized if not target.endswith(".py")
    )
    seconds = 0.0
    profiled = 0
    for node_id, duration in durations.items():
        path = node_id.split("::", 1)[0]
        if path in files or _matches_target(node_id, path, others):
            seconds += float(duration)
            profiled += 1
    return seconds, profiled


def _matches_target(node_id: str, path: str, targets: Sequence[str]) -> bool:
    """Whether *node_id* is under any directory or node-id target."""
    return any(
        node_id == target
        or node_id.startswith(f"{target}::")
        or path.startswith(f"{target}/")
        for target in targets
    )


def split_count(profiled_seconds: float, profiled_tests: int) -> int:
    """How many shards a selection of this size earns.

    One shard per :data:`MIN_SHARD_PROFILE_SECONDS` of profiled test time,
    rounded UP: the remainder past a whole budget is real test time that has
    to run somewhere, and because the profile undercounts, that remainder is
    itself a floor. Rounding it down hands a selection the narrower fan-out
    of the two readings every time.

    The count is then capped at the full suite's own shard count and at the
    number of tests the profile knows about: a group holding no test at all
    reports "no tests ran" instead of a verdict, so the count never exceeds
    what can fill it, and a selection with nothing profiled still runs on the
    one shard it always did.
    """
    earned = math.ceil(profiled_seconds / MIN_SHARD_PROFILE_SECONDS)
    return max(1, min(SHARD_COUNT, earned, profiled_tests))


@dataclass(frozen=True)
class SelectionEstimate:
    """One sizing of a selection against the full suite, from one profile.

    Selection shards and full CI shards share one runner setup and collect
    from the same roots, so their wall times differ only by the profiled
    test seconds each shard carries: comparing those compares the runs.
    """

    seconds: float
    tests: int
    suite_seconds: float

    @property
    def shards(self) -> int:
        return split_count(self.seconds, self.tests)

    @property
    def share(self) -> float:
        return self.seconds / self.suite_seconds if self.suite_seconds else 0.0

    @property
    def full_ci_reason(self) -> str:
        """Why full CI answers this selection instead; empty when it runs.

        With no profile there is nothing to compare, so the selection runs.
        The per-shard rule can only fire once FULL_CI_SHARE exceeds one
        full CI shard's share of the suite (1 / SHARD_COUNT).
        """
        if self.suite_seconds <= 0:
            return ""
        if self.share >= FULL_CI_SHARE:
            return (
                "selection_exceeds_full_ci_share: the selection profiles at "
                f"{self.seconds:.0f}s, {self.share:.0%} of the suite's "
                f"{self.suite_seconds:.0f}s (threshold {FULL_CI_SHARE:.0%})"
            )
        if self.seconds / self.shards >= self.suite_seconds / SHARD_COUNT:
            return (
                f"selection_not_faster_than_full_ci: each of its {self.shards} "
                f"shards carries {self.seconds / self.shards:.0f}s; full CI's "
                f"carry {self.suite_seconds / SHARD_COUNT:.0f}s"
            )
        return ""

    def summary(self) -> str:
        """One telemetry line: the selection, the suite, and the fan-out."""
        return (
            f"profiled_tests={self.tests} profiled_seconds={self.seconds:.0f} "
            f"suite_seconds={self.suite_seconds:.0f} share={self.share:.3f} "
            f"shards={self.shards}"
        )


def selection_estimate(root: Path, targets: Sequence[str]) -> SelectionEstimate:
    """Size *targets* and the whole suite against the same profile."""
    seconds, tests = profiled_size(root, targets)
    suite_seconds, _ = profiled_size(root, ["."])
    return SelectionEstimate(seconds, tests, suite_seconds)


__all__ = [
    "FULL_CI_SHARE",
    "MIN_SHARD_PROFILE_SECONDS",
    "SelectionEstimate",
    "normalize_profile_target",
    "profiled_size",
    "selection_estimate",
    "split_count",
]
