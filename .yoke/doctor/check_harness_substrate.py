"""HC-harness-substrate-drift: every renderer output and native view is current.

Calls ``yoke_core.domain.agents_render.detect_substrate_drift``, which names
every rendered harness file (Claude, Codex and Cursor agents, hooks, settings,
manifests) that differs from what the renderer would produce from the
canonical sources, and every native harness view (``.claude/agents``,
``.claude/rules``, ``.claude/skills/yoke``, ``.codex/hooks.json``,
``.codex/agents``, ``.cursor/agents``) that is missing or stale. A missing
``.codex/hooks.json`` means Codex loads no project hooks, so no tool call
records completion.

PASS — no drift.
FAIL — the detail names each drifted path and the repair command.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


_HC_NAME = "HC-harness-substrate-drift"
_HC_DESC = "All renderer outputs match canonical source"


def hc_harness_substrate_drift(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    from yoke_core.domain.agents_render import detect_substrate_drift

    repo_root = _resolve_repo_root()
    try:
        drifted = detect_substrate_drift(
            target_root=Path(repo_root) if repo_root else None,
        )
    except Exception as exc:
        rec.record(
            _HC_NAME, _HC_DESC, "FAIL",
            f"agents_render drift check raised: {exc}. Fix the named cause, "
            "then run `yoke agents render`.",
        )
        return

    if not drifted:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "all rendered harness outputs and native views match canonical source",
        )
        return

    detail_lines = ["rendered output or native view drifts from canonical source:"]
    detail_lines.extend(f"- {entry}" for entry in drifted)
    detail_lines.append("Run `yoke agents render` to repair.")
    rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(detail_lines))

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('harness-substrate-drift', 'All renderer outputs match canonical source', hc_harness_substrate_drift),
)
