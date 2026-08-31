"""Resolve which integration ref the boundary check is entitled to diff against.

The boundary obligation is constant: everything this item committed must
sit inside the coverage it declared. What differs by project shape is
what "the integration target" resolves to. A project with a remote is
integrating into ``refs/remotes/origin/<target>`` — that is the tree the
change will actually meet. A repository with no remote at all integrates
into its own ``refs/heads/<target>``, and that is a real answer, not a
degraded one.

What is *not* a real answer is neither ref resolving. The gate used to
treat that as nothing-to-enforce and pass, which made "the boundary was
clean" and "the boundary was never examined" the same outcome on the
item. Here it raises, and the refusal names both rungs, the ref each
one needed, and what to do about it.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

from yoke_core.domain.gate_satisfier_facts import (
    OBSERVED_LOCAL_INTEGRATION_REF,
    OBSERVED_REMOTE_INTEGRATION_REF,
    load_project_facts,
)
from yoke_core.domain.gate_satisfier_ladder import LadderResolution, require_rung
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    PATH_CLAIM_BOUNDARY_LADDER,
)
from yoke_core.domain.path_claims_boundary_git import (
    LOCAL_INTEGRATION_REF,
    REMOTE_INTEGRATION_REF,
    resolve_ref,
)


def probe_integration_refs(
    repo_path: str, integration_targets: Sequence[str],
) -> Dict[str, Tuple[bool, str]]:
    """Report which integration rung this worktree can actually reach.

    A rung counts as reachable only when EVERY target the item's claims
    name resolves through it. One claim silently falling back to a
    different base than its siblings would compare two items' work
    against two different trees under one verdict.
    """
    targets = [target for target in dict.fromkeys(integration_targets) if target]
    observed: Dict[str, Tuple[bool, str]] = {}
    for fact_key, template, label in (
        (OBSERVED_REMOTE_INTEGRATION_REF, REMOTE_INTEGRATION_REF, "remote"),
        (OBSERVED_LOCAL_INTEGRATION_REF, LOCAL_INTEGRATION_REF, "local"),
    ):
        unresolved = [
            target
            for target in targets
            if resolve_ref(repo_path, template.format(target=target)) is None
        ]
        if targets and not unresolved:
            observed[fact_key] = (
                True,
                f"{label} ref resolves for {', '.join(targets)} in {repo_path}",
            )
        else:
            missing = ", ".join(unresolved) or "no integration target recorded"
            observed[fact_key] = (
                False,
                f"{label} ref does not resolve for {missing} in {repo_path}",
            )
    return observed


def resolve_boundary_rung(
    conn: Any,
    *,
    project_id: int,
    item_id: int,
    repo_path: str,
    integration_targets: Sequence[str],
) -> LadderResolution:
    """Return the reachable boundary rung, or raise ``LadderUnsatisfied``."""
    facts = load_project_facts(
        conn,
        project_id,
        item_id=item_id,
        observed=probe_integration_refs(repo_path, integration_targets),
    )
    return require_rung(PATH_CLAIM_BOUNDARY_LADDER, facts)


__all__ = ["probe_integration_refs", "resolve_boundary_rung"]
