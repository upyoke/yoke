"""Refuse a candidate whose hosted consumer has not been proven against it.

The hosted host consumes this repo's universe app bundle across a declared
contract version. A change to that shared surface is only deliverable once
the real host build has run against the exact candidate — a producer-only
green run proves the producer and nothing else, and that is precisely how a
bundle declaring contract 7 reached a host implementing contract 6 and
stopped two hosted releases after the artifact had already been published.

This gate decides *when* consumer proof is required and adopts the
consumer's own conclusion as the answer; :mod:`platform_consumer_check`
owns reaching it. It is not a second validator.

Usage::

    python3 -m runtime.api.tools.require_platform_consumer_compatibility \\
        --candidate-sha <40-hex> --dispatch-key <key> \\
        [--applies-when-changed-since <ref>] [--decide-only] [--timeout SEC]

*candidate-sha* is the exact commit the consumer must build against, and it
must be a full 40-hex sha: a short sha is resolved by the consumer against
whatever it names there, which is the wrong-candidate green this gate
exists to make impossible.

*dispatch-key* binds one proof to one attempt. Retries inside an attempt
recover the same consumer run; a new attempt forces a fresh build against
the consumer's current trunk, so a proof never outlives the trunk it was
taken on and a moved main cannot ride older evidence.

*applies-when-changed-since* limits the gate to changes touching the
host-consumed surface, measured from the merge-base with that ref. Omit it
to demand proof unconditionally, which is what the release boundary does.

*consumer-ref* is the consumer branch to prove against, defaulting to its
trunk. A change that breaks the shared contract cannot be proven against
trunk by definition — trunk still implements the old contract, and the
consumer's own companion branch cannot be proven against the last published
product either, so demanding trunk on both sides deadlocks the pair. An
author therefore names the linked companion branch with a
``Consumer-candidate: <branch>`` trailer on a commit in the candidate range,
which this reads when a scope ref is given. Landing on that proof is safe
because the release boundary re-proves against trunk unconditionally: a pair
may merge in either order, and neither half can ship until both are on
trunk.

*decide-only* reports applicability and stops, so a caller can skip an
expensive setup it does not need. It writes ``applicable=true|false`` to
``$GITHUB_OUTPUT`` when that file is set.

Exits 0 when the pair is proven or the gate does not apply, 1 when the
consumer refused the candidate or its evidence does not name it, and 2 when
proof could not be obtained at all. Every non-zero exit fails the caller:
missing evidence is a refusal, never a pass.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from yoke_contracts.universe_asset_contract import UNIVERSE_ASSETS

from runtime.api.tools import platform_consumer_check as consumer

#: Where the host-consumed asset members live in this repository's tree.
_PACKAGE_SOURCE_ROOT = "packages/yoke-core/src/"
#: Declaration-emitting sources for the same contract, which change the
#: shared surface without changing a shipped asset byte-for-byte.
_CONTRACT_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/ui/contracts/"


def host_consumed_paths() -> Tuple[str, ...]:
    """Repository paths of the assets the host consumes, from one source."""
    return tuple(
        f"{_PACKAGE_SOURCE_ROOT}{asset.artifact_member}"
        for asset in UNIVERSE_ASSETS
    )


def touches_host_contract(paths: Sequence[str]) -> Tuple[str, ...]:
    """The changed paths that put the host-consumed contract in play."""
    consumed = set(host_consumed_paths())
    return tuple(
        path
        for path in paths
        if path in consumed or path.startswith(_CONTRACT_SOURCE_ROOT)
    )


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail or 'no output'}")
    return completed.stdout


def changed_paths(repo_root: Path, base_ref: str) -> Tuple[str, ...]:
    """Paths changed since the merge-base of HEAD and *base_ref*."""
    base = _git(repo_root, "merge-base", "HEAD", base_ref).strip()
    diff = _git(repo_root, "diff", "--name-only", "--diff-filter=ACMR", base, "HEAD")
    return tuple(line for line in diff.splitlines() if line)


#: Author-selected companion branch in the consumer repository, read from
#: the candidate's own commits so the selection is reviewable in the change
#: that needs it and travels with it.
_COMPANION_TRAILER = "Consumer-candidate:"


def companion_consumer_ref(repo_root: Path, base_ref: str) -> str:
    """The companion branch the candidate names, or the empty string.

    Only a scoped caller has a candidate range to read, which is what keeps
    companion selection a pull-request affair: the release boundary passes
    no scope and therefore always proves against trunk.
    """
    if not base_ref:
        return ""
    try:
        base = _git(repo_root, "merge-base", "HEAD", base_ref).strip()
        log = _git(repo_root, "log", "--format=%B", f"{base}..HEAD")
    except (OSError, RuntimeError):
        return ""
    for line in log.splitlines():
        stripped = line.strip()
        if stripped.startswith(_COMPANION_TRAILER):
            return stripped[len(_COMPANION_TRAILER):].strip()
    return ""


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    return cwd


def _append_summary(narrative: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write(f"## Consumer compatibility\n\n{narrative}\n")


def _write_output(key: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def _write_decision(applicable: bool) -> None:
    _write_output("applicable", "true" if applicable else "false")


def applicability(base_ref: str) -> Tuple[Optional[bool], str]:
    """Whether the gate applies, or why that could not be decided."""
    if not base_ref:
        return True, ""
    try:
        paths = changed_paths(_repo_root(), base_ref)
    except (OSError, RuntimeError) as exc:
        # An unresolvable scope is never a silent pass: a gate reporting
        # "nothing changed" because it could not look is indistinguishable
        # from one that looked, and that is the divergence it exists to close.
        return None, f"changed-path scope against {base_ref} unresolvable: {exc}"
    return bool(touches_host_contract(paths)), ""


def _parse(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="require_platform_consumer_compatibility",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--dispatch-key", default="")
    parser.add_argument("--applies-when-changed-since", default="")
    parser.add_argument("--consumer-ref", default="")
    parser.add_argument("--decide-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800, dest="timeout_sec")
    return parser.parse_args(list(sys.argv[1:] if argv is None else argv))


def _refuse(narrative: str, code: int) -> int:
    print(narrative, file=sys.stderr)
    _append_summary(narrative)
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse(argv)
    applies, undecidable = applicability(args.applies_when_changed_since)
    if applies is None:
        return _refuse(
            f"consumer compatibility unproven: {undecidable}", consumer.UNAVAILABLE
        )
    if not applies:
        note = (
            "host-consumed contract surface unchanged since "
            f"{args.applies_when_changed_since}; no consumer proof required"
        )
        print(note)
        _append_summary(note)
        _write_decision(False)
        return 0
    _write_decision(True)
    if args.decide_only:
        print("host-consumed contract surface changed; consumer proof required")
        return 0

    candidate = args.candidate_sha.strip().lower()
    if not consumer.FULL_SHA.match(candidate):
        return _refuse(
            "consumer compatibility unproven: --candidate-sha must be a full "
            f"40-hex commit, got {args.candidate_sha!r}. A short sha is "
            "resolved by the consumer against whatever it names there.",
            consumer.UNAVAILABLE,
        )
    if not args.dispatch_key.strip():
        return _refuse(
            "consumer compatibility unproven: --dispatch-key is required so "
            "one proof belongs to one attempt.",
            consumer.UNAVAILABLE,
        )

    consumer_ref = args.consumer_ref.strip() or companion_consumer_ref(
        _repo_root(), args.applies_when_changed_since,
    ) or consumer.CONSUMER_TRUNK_REF
    code, narrative, proven_revision = consumer.prove(
        candidate,
        dispatch_key=args.dispatch_key.strip(),
        timeout_sec=args.timeout_sec,
        consumer_ref=consumer_ref,
    )
    if code:
        return _refuse(narrative, code)
    # Named so a later stage can refuse to ship against a different one.
    _write_output("proven_consumer_sha", proven_revision)
    print(narrative)
    _append_summary(narrative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
