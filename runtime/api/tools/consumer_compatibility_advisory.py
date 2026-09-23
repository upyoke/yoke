"""Warn during tree contracts when the hosted consumer refuses a candidate.

Publication is where consumer proof is mandatory — see
:mod:`require_platform_consumer_compatibility`, which the release bridge runs
before it allocates the annotated tag. This is the earlier, advisory half:
it runs in its own independent CI job (see
``.github/workflows/consumer-compatibility-advisory.yml``) so an author
changing a surface the hosted service consumes gets an early signal rather
than first learning at the release, and it never decides any required check's
verdict — nor does the tree-contracts job or the shard matrix wait on it. A
fast landing can beat this advisory; the mandatory exact-pair release proof
remains the authority.

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
        --base origin/main --candidate-sha <40-hex>
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
#: Control-plane schema and boot-seed sources exercised by the hosted
#: consumer's pristine-tenant candidate check.
_CONTROL_PLANE_DOMAIN_ROOT = "packages/yoke-core/src/yoke_core/domain/"
_MODEL_REFERENCE_CONTRACT_ROOT = (
    "packages/yoke-contracts/src/yoke_contracts/model_reference_"
)

_ANNOTATION_TITLE = "consumer-compatibility"


def host_consumed_paths() -> Tuple[str, ...]:
    """Repository paths of the assets the host consumes, from one source."""
    return tuple(
        f"{_PACKAGE_SOURCE_ROOT}{asset.artifact_member}" for asset in UNIVERSE_ASSETS
    )


def _touches_control_plane_data(path: str) -> bool:
    """Whether *path* can change hosted control-plane schema or boot seeds."""
    if path.startswith(_MODEL_REFERENCE_CONTRACT_ROOT):
        return True
    if not path.startswith(_CONTROL_PLANE_DOMAIN_ROOT):
        return False

    relative = path[len(_CONTROL_PLANE_DOMAIN_ROOT) :]
    return (
        relative == "schema.py"
        or relative == "schema_init.py"
        or relative == "model_reference_store.py"
        or relative.startswith("schema_")
        or relative.endswith("_schema.py")
        or relative.startswith("migrations/")
    )


def touches_hosted_consumer_surface(paths: Sequence[str]) -> Tuple[str, ...]:
    """The changed paths that require the hosted consumer advisory."""
    consumed = set(host_consumed_paths())
    return tuple(
        path
        for path in paths
        if (
            path in consumed
            or path.startswith(_CONTRACT_SOURCE_ROOT)
            or _touches_control_plane_data(path)
        )
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

    touched = touches_hosted_consumer_surface(scope.paths)
    if not touched:
        _report(
            "not applicable — this change does not touch the surface the "
            "hosted service consumes"
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

    # No durable driver authority resolves an exact consumer commit here
    # (this runs on hosted CI, not the release bridge's own machine), so
    # this dispatches onto trunk by name and trusts the run's own report
    # instead of demanding an exact-pair match.
    code, narrative, _proven = gate.prove(
        candidate,
        gate.CONSUMER_TRUNK_REF,
        timeout_sec=args.timeout_sec,
        exact_pair=False,
    )
    _report(narrative, warn=bool(code))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
