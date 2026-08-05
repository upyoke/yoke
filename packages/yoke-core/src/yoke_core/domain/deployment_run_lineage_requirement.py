"""Refusing a deployment run at creation when it can never execute.

A run whose flow dispatches a GitHub Actions workflow needs an immutable
release lineage — a full commit SHA or an annotated release tag — because
the dispatch binds to an exact artifact rather than to whatever a branch
points at. That requirement was enforced only at execution, so creation
accepted runs that were guaranteed to fail.

The cost is not merely a late error. Creation succeeds, prints a run id,
and the operator drives it; execution then walks the earlier stages,
mutates run state, and refuses partway through, leaving a failed run in
the history that has to be abandoned and recreated. Refusing at creation
costs one clear message and leaves nothing behind.

The requirement is derived from the flow's own stages rather than from a
list of flow ids, so a flow that gains a dispatch stage inherits the
refusal without anyone remembering to update a roster.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: Stage runner that dispatches an external workflow against an exact ref.
DISPATCHING_STEP_RUNNER = "github-actions-workflow"

#: Shape of a full commit SHA. Anything shorter is ambiguous, and a branch
#: name is not immutable at all.
_SHA_LENGTH = 40
_SHA_CHARS = frozenset("0123456789abcdef")


class LineageRequiredError(ValueError):
    """A run was created without the lineage its flow will demand."""


def stages_dispatch_a_workflow(stages: Iterable[Any]) -> bool:
    """Whether any stage binds to an exact ref via an external dispatch."""
    for stage in stages or ():
        if not isinstance(stage, dict):
            continue
        if str(stage.get("step_runner") or "") == DISPATCHING_STEP_RUNNER:
            return True
    return False


def looks_immutable(lineage: str) -> bool:
    """Whether a lineage value names something that cannot move.

    A full SHA is immutable by construction. A tag name is accepted here
    and re-checked at dispatch, where the remote is available and a
    lightweight tag can be told from an annotated one — creation has no
    remote to ask, and refusing every tag would block the release train's
    own historical shape.
    """
    candidate = lineage.strip()
    if not candidate:
        return False
    hex_only = set(candidate.lower()) <= _SHA_CHARS
    if hex_only:
        # Full length is a commit. Shorter is an ABBREVIATED commit, which
        # resolves today and can become ambiguous as the repository grows —
        # it is not a tag just because it is not full length.
        return len(candidate) == _SHA_LENGTH
    # A tag, plausibly. Reject the shapes that are definitely a branch.
    return candidate not in {"main", "master", "HEAD"} and "/" not in candidate


def require_lineage_for_stages(
    stages: Iterable[Any],
    release_lineage: Optional[str],
    *,
    flow: str = "",
) -> None:
    """Refuse now what the dispatch stage would refuse later.

    Names the requirement and the way to satisfy it, because the operator
    reading this has a repository in front of them and needs to know that
    the lineage is bound mechanically from a ref rather than typed.
    """
    if not stages_dispatch_a_workflow(stages):
        return
    lineage = (release_lineage or "").strip()
    named = f" '{flow}'" if flow else ""
    if not lineage:
        raise LineageRequiredError(
            f"deployment flow{named} dispatches a workflow against an exact "
            "ref, so the run needs an immutable release_lineage and would "
            "fail at execution without one. Bind it at creation with "
            "--project-repo-path <git-toplevel> --source-ref <ref>."
        )
    if not looks_immutable(lineage):
        raise LineageRequiredError(
            f"release_lineage {lineage!r} names a moving ref; deployment "
            f"flow{named} dispatches against an exact commit or annotated "
            "release tag. Bind it with --project-repo-path <git-toplevel> "
            "--source-ref <ref>, which resolves the ref to its commit."
        )


__all__ = [
    "DISPATCHING_STEP_RUNNER",
    "LineageRequiredError",
    "looks_immutable",
    "require_lineage_for_stages",
    "stages_dispatch_a_workflow",
]
