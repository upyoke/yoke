"""Resumable onboarding checklist records for the product CLI."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_cli.config import machine_config
from yoke_cli.config.onboard_checklist_model import (
    CHECKLIST_LAYERS,
    CHECKLIST_STATUSES,
    ChecklistRow,
    ChecklistRun,
    ChecklistValidationError,
    build_init_payload,
    dumps_handoff_json,
    dumps_json,
    dumps_payload,
    render_project_view,
    transition_status,
)
from yoke_cli.config.onboard_checklist_render import (
    DEFAULT_VIEW_PATH,
    render_markdown,
)
from yoke_cli.config.onboard_checklist_schema import (
    BRANCH_MACHINE_ONLY,
    BRANCH_SOURCE_DEV_ADMIN,
    CHECKLIST_STATUSES as STATUSES,
    PROJECT_ROW_IDS,
    ROW_IDS,
    ROW_SPECS,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    SETUP_HANDOFF_ROW_ID,
    SOURCE_DEV_ROW_ID,
    STATUS_BLOCKED,
    STATUS_DEFERRED,
    STATUS_NEEDED,
    STATUS_NOT_NEEDED,
    STATUS_UNKNOWN,
    TERMINAL_STATUSES,
)

RUNS_DIR_NAME = "onboarding-runs"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class OnboardChecklistError(RuntimeError):
    """The onboarding checklist cannot be built or persisted."""


def build_report(
    *,
    run_id: str | None = None,
    branch: str,
    project_root: str | Path | None = None,
    project_id: int | None = None,
    project_slug: str | None = None,
    github_repo: str | None = None,
    row_status: Sequence[str] = (),
    evidence: Sequence[str] = (),
    blockers: Sequence[str] = (),
    notes: Sequence[str] = (),
    view_path: str | Path | None = None,
    write_view: bool = True,
) -> dict[str, Any]:
    """Create or resume a machine-local onboarding checklist run."""
    selected_id = _normalize_run_id(run_id or _new_run_id())
    record_path = run_record_path(selected_id)
    resumed = record_path.is_file()
    record = _load_record(record_path) if resumed else _new_record(selected_id)
    _update_metadata(
        record,
        branch=branch,
        project_root=project_root,
        project_id=project_id,
        project_slug=project_slug,
        github_repo=github_repo,
    )
    rows = _merge_rows(record.get("rows"), branch)
    _apply_row_values(rows, "status", _parse_assignments(row_status, "status"))
    _apply_row_values(rows, "evidence", _parse_assignments(evidence, "evidence"))
    _apply_row_values(rows, "blocker", _parse_assignments(blockers, "blocker"))
    _apply_row_values(rows, "note", _parse_assignments(notes, "note"))
    record["rows"] = rows
    record["summary"] = _summary(rows)
    record["doctor"] = _doctor(record, record_path, None)
    record["updated_at"] = _now_iso()
    _write_json(record_path, record)

    rendered_view: Path | None = None
    if write_view:
        rendered_view = _resolve_view_path(project_root, view_path)
        if rendered_view is not None:
            _write_text(rendered_view, render_markdown(record))
            record["doctor"] = _doctor(record, record_path, rendered_view)
            _write_json(record_path, record)
    return {
        "operation": "onboard.checklist",
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "resumed": resumed,
        "record_path": str(record_path),
        "view_path": str(rendered_view) if rendered_view else None,
        "run": record,
    }


def run_record_path(run_id: str) -> Path:
    return runs_dir() / f"{_normalize_run_id(run_id)}.json"


def runs_dir() -> Path:
    return machine_config.yoke_home() / RUNS_DIR_NAME


def _new_record(run_id: str) -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "branch": None,
        "project": {},
        "rows": [],
        "summary": {},
        "doctor": {},
        "secret_free": True,
    }


def _merge_rows(existing: Any, branch: str) -> list[dict[str, Any]]:
    existing_by_id = {
        str(row.get("row_id")): row for row in existing
        if isinstance(row, dict) and row.get("row_id") in ROW_IDS
    } if isinstance(existing, list) else {}
    rows: list[dict[str, Any]] = []
    for spec in ROW_SPECS:
        current = dict(existing_by_id.get(spec.row_id, {}))
        current.update({
            "row_id": spec.row_id,
            "step": spec.step,
            "phase": spec.title,
            "label": spec.title,
            "layer": spec.layer,
            "owner": spec.owner,
            "exit_condition": spec.hint,
            "hint": spec.hint,
        })
        current.setdefault("status", _default_status(spec.row_id, branch))
        current.setdefault("evidence", "")
        current.setdefault("blocker", "")
        current.setdefault("note", "")
        rows.append(current)
    return rows


def _default_status(row_id: str, branch: str) -> str:
    if branch == BRANCH_MACHINE_ONLY and row_id in PROJECT_ROW_IDS:
        return STATUS_DEFERRED
    if row_id == SOURCE_DEV_ROW_ID and branch != BRANCH_SOURCE_DEV_ADMIN:
        return STATUS_NOT_NEEDED
    if row_id == "later-per-item-facts":
        return STATUS_DEFERRED
    if row_id == SETUP_HANDOFF_ROW_ID:
        return STATUS_NEEDED
    return STATUS_NEEDED


def _update_metadata(
    record: dict[str, Any],
    *,
    branch: str,
    project_root: str | Path | None,
    project_id: int | None,
    project_slug: str | None,
    github_repo: str | None,
) -> None:
    record["branch"] = branch
    project = dict(record.get("project") or {})
    if project_root is not None:
        project["root"] = str(Path(project_root).expanduser())
    if project_id is not None:
        if int(project_id) <= 0:
            raise OnboardChecklistError("--project-id must be a positive integer")
        project["id"] = int(project_id)
    if project_slug:
        project["slug"] = project_slug
    if github_repo:
        project["github_repo"] = github_repo
    record["project"] = project


def _parse_assignments(values: Sequence[str], label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise OnboardChecklistError(f"{label} must use ROW=VALUE: {raw}")
        row_id, value = raw.split("=", 1)
        row_id = row_id.strip()
        if row_id not in ROW_IDS:
            raise OnboardChecklistError(
                f"unknown checklist row {row_id!r}; expected one of {', '.join(ROW_IDS)}"
            )
        parsed[row_id] = value.strip()
    return parsed


def _apply_row_values(rows: list[dict[str, Any]], key: str, values: Mapping[str, str]) -> None:
    if not values:
        return
    by_id = {row["row_id"]: row for row in rows}
    for row_id, value in values.items():
        if key == "status" and value not in STATUSES:
            raise OnboardChecklistError(
                f"invalid status {value!r}; expected one of {', '.join(STATUSES)}"
            )
        by_id[row_id][key] = value


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_status = {status: 0 for status in STATUSES}
    by_layer: dict[str, dict[str, int]] = {}
    open_rows: list[str] = []
    blocked_rows: list[str] = []
    for row in rows:
        status = str(row.get("status") or STATUS_UNKNOWN)
        layer = str(row.get("layer") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_layer.setdefault(layer, {}).setdefault(status, 0)
        by_layer[layer][status] += 1
        if status == STATUS_BLOCKED:
            blocked_rows.append(str(row["row_id"]))
        if status not in TERMINAL_STATUSES:
            open_rows.append(str(row["row_id"]))
    return {
        "by_status": by_status,
        "by_layer": by_layer,
        "open_rows": open_rows,
        "blocked_rows": blocked_rows,
        "open_row_count": len(open_rows),
        "blocked_row_count": len(blocked_rows),
    }


def _doctor(record: Mapping[str, Any], record_path: Path, view_path: Path | None) -> dict[str, Any]:
    summary = record.get("summary") or {}
    blocked = int(summary.get("blocked_row_count") or 0)
    open_count = int(summary.get("open_row_count") or 0)
    status = "blocked" if blocked else "ready" if open_count == 0 else "open"
    return {
        "readable": True,
        "status": status,
        "schema": SCHEMA_NAME,
        "record_path": str(record_path),
        "view_path": str(view_path) if view_path else None,
        "open_rows": list(summary.get("open_rows") or []),
        "blocked_rows": list(summary.get("blocked_rows") or []),
    }


def _resolve_view_path(project_root: str | Path | None, view_path: str | Path | None) -> Path | None:
    if view_path is not None:
        selected = Path(view_path).expanduser()
        if selected.is_absolute():
            return selected
        if project_root is None:
            raise OnboardChecklistError("--view-path must be absolute without --project-root")
        return Path(project_root).expanduser() / selected
    if project_root is None:
        return None
    return Path(project_root).expanduser() / DEFAULT_VIEW_PATH


def _load_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OnboardChecklistError(f"cannot read onboarding run {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_NAME:
        raise OnboardChecklistError(f"{path} is not a Yoke onboarding checklist run")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_run_id(run_id: str) -> str:
    selected = run_id.strip()
    if not _RUN_ID_RE.match(selected):
        raise OnboardChecklistError(
            "run id must start with an alphanumeric character and contain only letters, digits, dots, underscores, or dashes"
        )
    return selected


def _new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "DEFAULT_VIEW_PATH",
    "CHECKLIST_LAYERS",
    "CHECKLIST_STATUSES",
    "ChecklistRow",
    "ChecklistRun",
    "ChecklistValidationError",
    "OnboardChecklistError",
    "RUNS_DIR_NAME",
    "build_init_payload",
    "build_report",
    "dumps_handoff_json",
    "dumps_json",
    "dumps_payload",
    "render_project_view",
    "run_record_path",
    "runs_dir",
    "transition_status",
]
