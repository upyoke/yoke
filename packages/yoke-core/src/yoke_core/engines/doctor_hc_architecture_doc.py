"""HC-architecture-model-doc-drift — verify AGENTS.md `## Architecture
Model` documents every payload concept.

The architecture model is dual-surfaced: machine-checkable via the
``architecture_model`` Project Structure family payload AND
human-readable via the AGENTS.md `## Architecture Model` section. The
two must agree — when an operator adds a layer, domain, or
cross-cutting entrypoint to the payload, the doc surface must mention
it by name so agents reading either path get the same answer.

The HC is a simple text-substring check:

* Every layer id in ``architecture_model.payload.layers`` must appear
  in the doc.
* Every cross-cutting entrypoint key must appear in the doc.

A more sophisticated rendered-table comparison can replace the
substring check later; the substring shape is sufficient to catch the
common drift mode (added a payload concept, forgot to update the doc).

Self-skips when the AGENTS.md file is absent or the
``architecture_model`` row is not set.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from yoke_core.engines.doctor_hc_architecture_helpers import (
    format_findings,
    load_architecture_model,
)


_DOC_DRIFT = "HC-architecture-model-doc-drift"
_DOC_DRIFT_DESC = (
    "AGENTS.md `## Architecture Model` section drifts from the live "
    "architecture_model payload"
)
_AGENTS_FILE = Path("AGENTS.md")
_ARCH_HEADING = "## Architecture Model"


def _read_agents_md() -> str:
    if not _AGENTS_FILE.exists():
        return ""
    try:
        return _AGENTS_FILE.read_text()
    except OSError:
        return ""


def hc_architecture_model_doc_drift(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    model = load_architecture_model(conn, args.project)
    if model is None:
        rec.record(_DOC_DRIFT, _DOC_DRIFT_DESC, "PASS",
                   "architecture_model not set for project — skipping")
        return
    text = _read_agents_md()
    if not text:
        rec.record(_DOC_DRIFT, _DOC_DRIFT_DESC, "PASS",
                   "AGENTS.md missing — skipping")
        return
    if _ARCH_HEADING not in text:
        rec.record(_DOC_DRIFT, _DOC_DRIFT_DESC, "WARN",
                   f"- AGENTS.md missing `{_ARCH_HEADING}` heading. "
                   "Repair: add the section per the rendered payload.")
        return
    findings: List[str] = []
    for layer in model.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        lid = str(layer.get("id") or "")
        if lid and lid not in text:
            findings.append(
                f"- Layer `{lid}` is in the payload but missing from "
                "AGENTS.md `## Architecture Model`. Repair: add the "
                "layer to the section's Layer vocabulary block."
            )
    entrypoints = model.get("cross_cutting_entrypoints") or {}
    for ep_name in entrypoints:
        if ep_name not in text:
            findings.append(
                f"- Cross-cutting entrypoint `{ep_name}` is in the "
                "payload but missing from AGENTS.md `## Architecture "
                "Model`. Repair: add the entrypoint to the Cross-"
                "cutting entrypoints table."
            )
    if not findings:
        rec.record(_DOC_DRIFT, _DOC_DRIFT_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} drift entry/entries between "
        "architecture_model.payload and AGENTS.md `## Architecture Model`."
    )
    rec.record(_DOC_DRIFT, _DOC_DRIFT_DESC, "WARN",
               format_findings(head, findings))
    # Silence unused-imports lint for json (kept for future rendered-table comparison).
    _ = json


__all__ = ["hc_architecture_model_doc_drift"]
