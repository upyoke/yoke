"""Bind one source commit for every flow in a release set.

A set releases one commit on several flows. Binding it from a flow that does
not wait for CI picks the gate branch tip without asking for a run of its own,
and a later flow that does wait then refuses that tip as untested. So a flow
that waits for CI binds first: a tip with no run of its own gets one dispatch,
and every other flow checks that same commit.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.deployment_run_ci_tested_source import (
    bind_tested_release_source,
    ci_gate_target,
    require_tested_lineage,
)


def bind_set_source(
    project: str, flows: list[str], release_lineage: Optional[str]
) -> Optional[str]:
    """The commit every flow in the set releases, or ``None`` when none binds one.

    Raises :class:`~yoke_core.domain.deployment_run_ci_tested_source.ReleaseSourceRefused`
    when any flow's CI gate could not pass that commit.
    """
    if (release_lineage or "").strip():
        for flow in flows:
            require_tested_lineage(project, flow, None, release_lineage)
        return release_lineage
    waiting = [
        flow for flow in flows if ci_gate_target(project, flow, None, ci_only=True)
    ]
    selected: Optional[str] = None
    for flow in [*waiting, *(flow for flow in flows if flow not in waiting)]:
        if selected:
            require_tested_lineage(project, flow, None, selected)
        else:
            selected = bind_tested_release_source(project, flow, None, None)
    return selected


__all__ = ["bind_set_source"]
