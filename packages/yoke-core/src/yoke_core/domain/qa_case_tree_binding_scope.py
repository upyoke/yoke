"""Which tree a QA case is judged against, and how that is proved.

:mod:`yoke_core.domain.verification_tree_binding` binds a verification run to
the worktree the session holds a claim on, because a green collected in the
main checkout while the claimed lane sits untouched reports on code nobody
changed. That reasoning needs the run to be *about* the claimed lane.

A deployment-run case is not. Its subject is the run: a candidate revision
already built, deployed, and observed at an endpoint the run's own stage
receipt recorded. No member's lane contributed to it, and no lane could be
the "right" tree for it, so comparing it against whichever item claim the
executing session happens to hold refuses every routine invocation and sends
its owner to ``--allow-tree-mismatch`` — the flag reserved for a deliberate
cross-tree run, which then stops meaning anything.

Dropping the comparison outright is the other error. A deployment case runs
a command in a checkout, and some of those commands read the repository; a
verdict collected from a tree that is not the candidate cannot speak for the
candidate's code, and saying nothing about it is how a silent pass happens.
So the tree comparison is not removed but re-pointed: the authority is the
run's own candidate revision, which the execution target records. A checkout
sitting at that revision needs no flag, which is the ordinary case for an
owner supplying evidence right after the release. A checkout that has moved
is refused and names both revisions, with ``--allow-tree-mismatch`` reserved
for its true meaning here — a case that reads nothing from the checkout,
such as a probe against a deployed endpoint.

A binding this cannot evaluate refuses rather than proceeding. Elsewhere an
unanswerable lookup is a notice, because the thing being checked is a
coordination fact and the run itself is still meaningful; here the missing
fact IS the evidence's subject, so "which code did this verdict cover?" has
no answer at all. Every deployment run carries its candidate revision and
every checkout has a HEAD, so this fires only on a real fault.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.verification_tree_binding_messages import (
    ALLOW_TREE_MISMATCH_FLAG,
    CHECKOUT_PATH_FLAG,
)

#: How much of a revision a refusal prints. Full SHAs make the two sides
#: hard to compare at a glance; the comparison itself is always exact.
_SHORT = 12


@dataclass(frozen=True)
class DeploymentBinding:
    """What to say about a deployment case's tree, and whether to refuse."""

    notice: str = ""
    refusal: str = ""


def session_lane_binds_case(case: Mapping[str, Any]) -> bool:
    """Return whether this case's verdict is about the session's own lane."""
    return case.get("item_id") is not None


def candidate_revision(case: Mapping[str, Any]) -> str:
    """The revision this run deployed, as its execution target recorded it."""
    target = case.get("execution_target")
    target = target if isinstance(target, Mapping) else {}
    deployment = target.get("deployment")
    deployment = deployment if isinstance(deployment, Mapping) else {}
    return str(deployment.get("release_lineage") or "").strip()


def _subject(case: Mapping[str, Any]) -> str:
    target = case.get("execution_target")
    target = target if isinstance(target, Mapping) else {}
    deployment = target.get("deployment")
    deployment = deployment if isinstance(deployment, Mapping) else {}
    run_id = str(deployment.get("run_id") or case.get("deployment_run_id") or "")
    stage = str(deployment.get("stage") or case.get("deployment_stage") or "")
    return f"deployment run {run_id!r} stage {stage!r}"


def evaluate_deployment_binding(
    *,
    surface: str,
    case: Mapping[str, Any],
    tree: str,
    head_sha: str,
    allow_mismatch: bool = False,
) -> DeploymentBinding:
    """Judge a deployment-run case's checkout against the run's candidate."""
    subject = _subject(case)
    candidate = candidate_revision(case)
    if not candidate or not head_sha:
        missing = (
            "its execution target records no candidate revision"
            if not candidate
            else f"'{tree}' has no readable HEAD"
        )
        if allow_mismatch:
            return DeploymentBinding(
                notice=(
                    f"{surface}: {ALLOW_TREE_MISMATCH_FLAG} — {subject} is "
                    f"bound to the candidate it deployed, but {missing}. Taken "
                    "as a declaration that this case reads nothing from the "
                    "checkout; its verdict says nothing about repository "
                    "content."
                )
            )
        return DeploymentBinding(
            refusal=(
                f"{surface} TREE-BINDING REFUSAL: {subject} is bound to the "
                f"candidate it deployed, but {missing}, so which code this "
                "verdict covers cannot be established. A run always records "
                "its candidate and a checkout always has a HEAD, so this is a "
                "fault rather than a missing option.\n"
                f"Repair the checkout at '{tree}' (or the run's recorded "
                "candidate) and re-run, or pass "
                f"{ALLOW_TREE_MISMATCH_FLAG} only when this case reads nothing "
                "from the checkout, such as a probe against the deployed "
                "endpoint."
            )
        )
    if head_sha == candidate:
        return DeploymentBinding(
            notice=(
                f"{surface}: {subject} — '{tree}' is the candidate this run "
                f"deployed ({candidate[:_SHORT]}), which is what this verdict "
                "covers. No claimed worktree binds it."
            )
        )
    divergence = (
        f"{subject} deployed candidate {candidate[:_SHORT]}, but this run "
        f"would execute in '{tree}', which is at {head_sha[:_SHORT]}"
    )
    if allow_mismatch:
        return DeploymentBinding(
            notice=(
                f"{surface}: {ALLOW_TREE_MISMATCH_FLAG} — {divergence}. Taken "
                "as a declaration that this case reads nothing from the "
                "checkout; its verdict says nothing about repository content."
            )
        )
    return DeploymentBinding(
        refusal=(
            f"{surface} TREE-BINDING REFUSAL: {divergence}. A command that "
            "reads the repository would report on code this run never "
            "deployed.\n"
            "To verify the candidate, materialize a separate checkout pinned "
            f"to that revision and pass {CHECKOUT_PATH_FLAG} to "
            "`yoke qa plan run` or `yoke qa case run`. Do not mutate a shared "
            "project checkout other sessions depend on. Example against a "
            "disposable tree:\n"
            f'  git -C "/path/to/candidate-checkout" fetch origin {candidate}\n'
            f'  git -C "/path/to/candidate-checkout" checkout {candidate}\n'
            f"  yoke qa plan run ... {CHECKOUT_PATH_FLAG} "
            f"/path/to/candidate-checkout\n"
            f"Or pass {ALLOW_TREE_MISMATCH_FLAG} when this case reads nothing "
            "from the checkout, such as a probe against the deployed endpoint."
        )
    )


__all__ = [
    "DeploymentBinding",
    "candidate_revision",
    "evaluate_deployment_binding",
    "session_lane_binds_case",
]
