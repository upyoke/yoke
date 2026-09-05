"""Warn during tree contracts when the hosted consumer refuses a candidate.

Publication is where consumer proof is mandatory — see
:mod:`require_platform_consumer_compatibility`, which the release bridge runs
before it allocates the annotated tag. This is the earlier, advisory half:
it runs inside the repo-contracts job so an author changing the shared
universe app surface learns at the merge attempt rather than at the release,
and it never decides that job's verdict.

Three outcomes, and the difference between them is the point:

* **not applicable** — the change does not touch the surface the host
  consumes, so there is nothing to prove.
* **not checked** — no scoped consumer credential reached this run. A fork
  pull request never receives one, and public CI stays fully usable without
  it, so this says so plainly instead of implying a clean answer.
* **checked** — the consumer's own required check built its host against
  this exact candidate, and its conclusion is reported. A refusal names both
  revisions and the run.

Only the third outcome can be a non-zero exit, and the step that runs this
continues past it: this is a warning, not a gate.

Usage::

    python3 -m runtime.api.tools.consumer_compatibility_advisory \\
        --base origin/main --candidate-sha <40-hex> --dispatch-key <key>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from yoke_contracts.universe_asset_contract import UNIVERSE_ASSETS
from yoke_core.tools.ci_repo_contracts import resolve_changed_path_scope

from runtime.api.tools import require_platform_consumer_compatibility as gate

#: Where the host-consumed asset members live in this repository's tree.
_PACKAGE_SOURCE_ROOT = "packages/yoke-core/src/"
#: Declaration-emitting sources for the same contract, which change the
#: shared surface without changing a shipped asset byte-for-byte.
_CONTRACT_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/ui/contracts/"

_ANNOTATION_TITLE = "consumer-compatibility"


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


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    return cwd


def _report(message: str, *, warn: bool = False) -> None:
    print(f"consumer-compatibility: {message}", flush=True)
    if warn:
        print(f"::warning title={_ANNOTATION_TITLE}::{message}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"- **{_ANNOTATION_TITLE}**: {message}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="consumer_compatibility_advisory",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base", default="")
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--dispatch-key", default="")
    parser.add_argument("--timeout", type=int, default=1800, dest="timeout_sec")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    base = args.base.strip()
    try:
        scope = resolve_changed_path_scope(_repo_root(), base)
    except (OSError, RuntimeError) as exc:
        # Unreadable scope is reported, never treated as "nothing changed":
        # an advisory that goes quiet because it could not look is the same
        # silence the publication gate exists to stop being the first news.
        _report(
            f"not checked — changed-path scope against {base or '<unset>'} "
            f"was unresolvable: {exc}",
            warn=True,
        )
        return 0

    touched = touches_host_contract(scope.paths)
    if not touched:
        _report(
            "not applicable — this change does not touch the surface the "
            "hosted host consumes"
        )
        return 0

    candidate = args.candidate_sha.strip().lower()
    if not gate.is_full_commit_sha(candidate):
        _report(
            "not checked — no full 40-hex candidate commit was supplied, and "
            "the consumer resolves anything shorter against whatever it names "
            "there",
            warn=True,
        )
        return 0
    if not os.environ.get(gate.CONSUMER_TOKEN_ENV, "").strip():
        _report(
            "NOT CHECKED — this change touches "
            f"{', '.join(touched)}, and no scoped consumer credential reached "
            "this run, so the hosted host was not built against it. A fork "
            "pull request never receives that credential; the pair is proven "
            "before publication either way, and a maintainer can run the "
            "check from a branch in this repository.",
            warn=True,
        )
        return 0

    code, narrative, _proven = gate.prove(
        candidate,
        dispatch_key=args.dispatch_key.strip() or candidate,
        timeout_sec=args.timeout_sec,
    )
    _report(narrative, warn=bool(code))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
