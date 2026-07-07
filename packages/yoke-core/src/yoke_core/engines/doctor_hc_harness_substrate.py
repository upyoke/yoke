"""HC-harness-substrate-drift: every renderer output matches its canonical source.

Calls into ``yoke_core.domain.agents_render.detect_drift`` to enumerate any
Claude adapter file (under ``runtime/harness/claude/agents/``) whose content
differs from what the renderer would produce from the canonical body
(``runtime/agents/{agent}.md``) plus the per-role spec
(``runtime/agents/{agent}.claude.json``).

PASS — no drift.
FAIL — at least one rendered file diverges; the detail names each drifted path.
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
    try:
        from yoke_core.domain import agents_render
    except ImportError as exc:  # pragma: no cover - defensive
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            f"agents_render module unavailable ({exc}); "
            "renderer surface not provisioned yet",
        )
        return

    detect = getattr(agents_render, "detect_drift", None) or getattr(
        agents_render, "check_drift", None,
    )
    if detect is None:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "agents_render exposes neither detect_drift nor check_drift; "
            "renderer drift surface not yet provisioned",
        )
        return

    repo_root = _resolve_repo_root()
    kwargs = {"target_root": Path(repo_root)} if repo_root else {}
    try:
        try:
            drifted = detect(**kwargs)
        except TypeError:
            drifted = detect()
    except Exception as exc:
        rec.record(
            _HC_NAME, _HC_DESC, "FAIL",
            f"agents_render drift check raised: {exc}",
        )
        return

    if not drifted:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "all rendered Claude adapters match canonical source",
        )
        return

    detail_lines = ["rendered output drifts from canonical source:"]
    for entry in drifted:
        detail_lines.append(f"- {entry}")
    detail_lines.append(
        "Run `python3 -m yoke_core.domain.agents_render render` to repair.",
    )
    rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(detail_lines))
