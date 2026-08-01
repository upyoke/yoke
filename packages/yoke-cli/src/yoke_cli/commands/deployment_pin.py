"""Compare a candidate ref's version pin against an environment's live pin.

Some projects carry a plain-text version pin in their own repository — a
file naming the exact version of another component that environment runs.
The pin advances as a commit on the environment's branch, which makes it
ordinary repository content and therefore easy to regress by accident: a
ref captured before a pin bump still carries the older version, and
deploying that ref silently rolls the pinned component back.

The comparison lives beside the caller's checkout because both sides of it
are refs in that repository, which the control plane never sees. The rule
is generic — a deploy must not regress a version pin — while the pin's
location and its branch-per-environment mapping are project configuration,
declared by the project's ``release_pin`` capability:

    {
      "pin_file": "yoke-release-pin.txt",
      "branch_by_environment": {"stage": "stage", "production": "main"}
    }

A project without that capability is unaffected. When the declaration is
present but the pin cannot be read on either side, the comparison reports
that it was skipped rather than guessing — an unreadable pin is not
evidence that the move is safe, but it is also not evidence of a
regression, and refusing every unreadable case would block projects whose
pin file legitimately does not exist yet on a new branch.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

RELEASE_PIN_CAPABILITY = "release_pin"


class PinRegressionError(Exception):
    """A deployment would move the environment's pin to an older version."""


@dataclass(frozen=True)
class PinComparison:
    """Outcome of comparing a candidate ref's pin against the live pin."""

    regressed: bool
    candidate: Optional[str] = None
    current: Optional[str] = None
    branch: Optional[str] = None
    skipped_reason: Optional[str] = None


def read_pin_at_ref(repo_path: str, ref: str, pin_file: str) -> Optional[str]:
    """The pin file's contents at *ref*, or None when it cannot be read."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{ref}:{pin_file}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _version_key(value: str) -> tuple:
    """Sortable key for a pin string.

    Digit runs compare numerically so ``launch.9`` orders below
    ``launch.10``; everything else compares as text. Anything unparseable
    still yields a stable key, so two pins are always comparable even when
    a project's version scheme is not one this module has seen.
    """
    parts: list[tuple[int, Any]] = []
    for chunk in re.findall(r"\d+|\D+", value.strip()):
        if chunk.isdigit():
            parts.append((1, int(chunk)))
        else:
            parts.append((0, chunk))
    return tuple(parts)


def compare_pins(candidate: str, current: str) -> int:
    """-1 when *candidate* is older than *current*, 0 equal, 1 newer."""
    a, b = _version_key(candidate), _version_key(current)
    if a == b:
        return 0
    return -1 if a < b else 1


def evaluate_pin_move(
    *,
    settings: dict,
    repo_path: str,
    source_ref: str,
    target_env: str,
) -> PinComparison:
    """Compare the pin at *source_ref* against the environment's live pin."""
    pin_file = str(settings["pin_file"])
    branches = settings.get("branch_by_environment") or {}
    branch = branches.get(target_env)
    if not branch:
        return PinComparison(
            regressed=False,
            skipped_reason=(
                f"no pin branch declared for environment {target_env!r}"
            ),
        )
    candidate = read_pin_at_ref(repo_path, source_ref, pin_file)
    current = read_pin_at_ref(repo_path, f"origin/{branch}", pin_file)
    if candidate is None or current is None:
        missing = "source ref" if candidate is None else f"origin/{branch}"
        return PinComparison(
            regressed=False,
            candidate=candidate,
            current=current,
            branch=branch,
            skipped_reason=f"{pin_file} is unreadable at {missing}",
        )
    return PinComparison(
        regressed=compare_pins(candidate, current) < 0,
        candidate=candidate,
        current=current,
        branch=branch,
    )


def assert_no_pin_regression(
    *,
    settings: dict,
    repo_path: Optional[str],
    source_ref: Optional[str],
    target_env: Optional[str],
) -> Optional[PinComparison]:
    """Raise when the proposed ref would roll the environment's pin back.

    Returns the comparison when one was performed (so callers can report a
    skip reason), or None when the caller supplied no ref to compare.
    """
    if not repo_path or not source_ref or not target_env:
        return None
    comparison = evaluate_pin_move(
        settings=settings,
        repo_path=repo_path,
        source_ref=source_ref,
        target_env=target_env,
    )
    if comparison.regressed:
        raise PinRegressionError(
            f"{settings['pin_file']} at {source_ref} pins "
            f"{comparison.candidate}, older than {comparison.current} live on "
            f"origin/{comparison.branch}. Deploying this ref would roll the "
            "pinned version backward — fetch the pin branch and deploy a ref "
            "that includes the current pin, or pass the override flag when "
            "the rollback is intentional."
        )
    return comparison


__all__ = [
    "PinComparison",
    "PinRegressionError",
    "RELEASE_PIN_CAPABILITY",
    "assert_no_pin_regression",
    "compare_pins",
    "evaluate_pin_move",
    "read_pin_at_ref",
]
