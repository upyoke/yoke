"""Pure product-wheel onboarding checklist helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_contracts.onboard_checklist import (
    CHECKLIST_LAYERS,
    CHECKLIST_STATUSES,
    HANDOFF_TO,
    OPERATION,
    OPERATION_INIT,
    ROW_SPECS,
    SCHEMA_VERSION,
    STATUS_NEEDED,
)


class ChecklistValidationError(ValueError):
    """Checklist row status/layer is outside the shared vocabulary."""


@dataclass(frozen=True)
class ChecklistRow:
    id: str
    layer: str
    title: str
    status: str
    hint: str | None = None
    details: Sequence[str] = ()
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _validate_status(self.status)
        if self.layer not in CHECKLIST_LAYERS:
            raise ChecklistValidationError(
                f"invalid layer {self.layer!r}; expected one of {', '.join(CHECKLIST_LAYERS)}"
            )
        object.__setattr__(self, "details", tuple(self.details or ()))


@dataclass(frozen=True)
class ChecklistRun:
    machine_config_path: str | Path
    checkout_path: str | Path | None = None
    project_id: int | None = None
    rows: Sequence[ChecklistRow] = ()


def transition_status(
    row: ChecklistRow,
    status: str,
    *,
    evidence: Mapping[str, Any] | None = None,
) -> ChecklistRow:
    _validate_status(status)
    return replace(row, status=status, evidence=evidence)


def dumps_json(run: ChecklistRun) -> str:
    return json.dumps(_run_payload(run), indent=2, sort_keys=True) + "\n"


def dumps_handoff_json(run: ChecklistRun) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "handoff_to": HANDOFF_TO,
        "machine_config_path": str(run.machine_config_path),
        "checkout": {
            "path": str(run.checkout_path) if run.checkout_path else None,
            "project_id": run.project_id,
        },
        "rows": [_row_payload(row, compact=True) for row in run.rows],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_project_view(run: ChecklistRun) -> str:
    lines = [
        "# Yoke Onboarding Checklist",
        "",
        f"- Handoff: `{HANDOFF_TO}`",
        f"- Machine config: `{run.machine_config_path}`",
        "",
        "| Row | Layer | Status | Evidence |",
        "|---|---|---|---|",
    ]
    for row in run.rows:
        evidence = _redact(row.evidence) if row.evidence else row.hint or ""
        lines.append(
            f"| {row.title} | {row.layer} | {row.status} | "
            f"{_escape(str(evidence))} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_init_payload(
    *,
    machine_config_path: str | Path,
    checkout_path: str | Path | None,
    project_id: int | None,
) -> dict[str, Any]:
    run = ChecklistRun(
        machine_config_path=machine_config_path,
        checkout_path=checkout_path,
        project_id=project_id,
        rows=[
            ChecklistRow(
                id=spec.row_id,
                layer=spec.layer,
                title=spec.title,
                status=STATUS_NEEDED,
                hint=spec.hint,
            )
            for spec in ROW_SPECS
        ],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": OPERATION_INIT,
        "machine_config_path": str(machine_config_path),
        "checkout": {
            "path": str(checkout_path) if checkout_path else None,
            "project_id": project_id,
        },
        "status_vocabulary": list(CHECKLIST_STATUSES),
        "layers": list(CHECKLIST_LAYERS),
        "rows": [_row_payload(row) for row in run.rows],
        "handoff": json.loads(dumps_handoff_json(run)),
    }


def dumps_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _run_payload(run: ChecklistRun) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "operation": OPERATION,
        "machine_config_path": str(run.machine_config_path),
        "checkout_path": str(run.checkout_path) if run.checkout_path else None,
        "project_id": run.project_id,
        "rows": [_row_payload(row) for row in run.rows],
    }
    return {key: value for key, value in payload.items() if value is not None}


def _row_payload(row: ChecklistRow, *, compact: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "layer": row.layer,
        "title": row.title,
        "status": row.status,
    }
    if not compact:
        if row.hint:
            payload["hint"] = row.hint
        if row.details:
            payload["details"] = list(row.details)
        if row.evidence is not None:
            payload["evidence"] = dict(row.evidence)
    return payload


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ("token", "secret", "password", "key")):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _validate_status(status: str) -> None:
    if status not in CHECKLIST_STATUSES:
        raise ChecklistValidationError(
            f"invalid status {status!r}; expected one of {', '.join(CHECKLIST_STATUSES)}"
        )


__all__ = [
    "CHECKLIST_LAYERS",
    "CHECKLIST_STATUSES",
    "ChecklistRow",
    "ChecklistRun",
    "ChecklistValidationError",
    "build_init_payload",
    "dumps_handoff_json",
    "dumps_json",
    "dumps_payload",
    "render_project_view",
    "transition_status",
]
