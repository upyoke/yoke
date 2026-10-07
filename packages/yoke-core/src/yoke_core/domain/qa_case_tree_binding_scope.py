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
revision the run shipped for the case's own project -- its release lineage,
or, for a member of a project the run binds, the source it recorded for that
project. With no explicit tree the runner checks that revision out itself
(:mod:`yoke_core.domain.qa_candidate_checkout`), so the ordinary run needs no
flag however far the default branch has moved. An explicit
``--checkout-path`` at another revision is refused and names both, with
``--allow-tree-mismatch`` reserved for its true meaning here — a case that
reads nothing from the checkout, such as a probe against a deployed
endpoint.

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
    return case.get("public_ref") is not None


def candidate_revision(case: Mapping[str, Any]) -> str:
    """The revision this run shipped for the case's own project.

    A run carries one commit per project: its own lineage, plus the source it
    bound for each other project. A member of a bound project is checked out
    in that project's repository, so its checkout answers to the bound
    commit the server names as ``deployment_source_revision``. A server that
    predates that field leaves only the run's own lineage to compare against.
    """
    source = str(case.get("deployment_source_revision") or "").strip()
    if source:
        return source
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
    project = str(case.get("project") or "").strip()
    shipped = f"{project} at {candidate[:_SHORT]}" if project else candidate[:_SHORT]
    divergence = (
        f"{subject} deployed {shipped}, but this run "
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
            f"Re-run the same command without {CHECKOUT_PATH_FLAG}: the runner "
            "then checks the candidate out into a disposable tree, runs the "
            "case there and removes it, with no claim on any shared checkout. "
            f"Pass {ALLOW_TREE_MISMATCH_FLAG} only when this case reads nothing "
            "from the checkout, such as a probe against the deployed endpoint."
        )
    )


__all__ = [
    "DeploymentBinding",
    "candidate_revision",
    "evaluate_deployment_binding",
    "session_lane_binds_case",
]
