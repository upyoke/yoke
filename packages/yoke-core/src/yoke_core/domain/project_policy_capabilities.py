"""DB-backed default project policy capabilities.

Project behavior that must be shared by every checkout lives in
``project_capabilities.settings``.  This module owns the default rows and
idempotent repair used by DB init, project upsert, installer refresh, and the
one-shot migration wrapper for already-running installs.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from yoke_contracts.project_contract.project_keys import (
    LOCAL_PROJECT_KEYS,
    RECOGNIZED_PROJECT_KEYS,
)

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import row_value


PROJECT_POLICY_CAPABILITY = "project-policy"
SESSION_ROUTING_CAPABILITY = "session-routing"

_INT_POLICY_KEYS = frozenset({
    "wip_cap",
    "merge_conflict_threshold",
    "max_attempts",
    "file_line_limit",
})

_PROJECT_POLICY_KEYS = tuple(
    key for key in RECOGNIZED_PROJECT_KEYS if key not in LOCAL_PROJECT_KEYS
)

_SESSION_ROUTING_DEFAULTS: dict[str, Any] = {
    "executor_default_lanes": {
        "claude*": "DARIUS",
        "codex*": "ALTMAN",
        "DARIUS": "DARIUS",
        "ALTMAN": "ALTMAN",
    },
    "lane_paths": {
        "DARIUS": [
            "shepherd",
            "advance",
            "conduct",
            "refine",
            "polish",
            "usher",
            "strategize",
            "feed",
            "doctor",
        ],
        "ALTMAN": [
            "refine",
            "polish",
            "usher",
        ],
    },
    "process_offers": {
        "default": False,
        "strategize": False,
        "feed": False,
        "doctor": False,
    },
}


@dataclass(frozen=True)
class CapabilityRepairResult:
    """One capability row's repair outcome."""

    capability: str
    created: bool
    repaired_keys: tuple[str, ...]

    @property
    def reused(self) -> bool:
        return not self.created and not self.repaired_keys

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "created": self.created,
            "repaired_keys": list(self.repaired_keys),
            "reused": self.reused,
        }


def project_policy_defaults(
    conn: Any | None = None,
    project_id: int | None = None,
    *,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Return default ``project-policy`` settings for a project."""

    defaults: dict[str, Any] = {}
    for key in _PROJECT_POLICY_KEYS:
        raw = RECOGNIZED_PROJECT_KEYS[key][0]
        defaults[key] = int(raw) if key in _INT_POLICY_KEYS else raw

    resolved_base_branch = (base_branch or "").strip()
    if not resolved_base_branch and conn is not None and project_id is not None:
        row = conn.execute(
            f"SELECT default_branch FROM projects WHERE id={_p(conn)}",
            (int(project_id),),
        ).fetchone()
        if row is not None:
            resolved_base_branch = str(
                row_value(row, "default_branch", 0) or ""
            ).strip()
    if resolved_base_branch:
        defaults["base_branch"] = resolved_base_branch
    return defaults


def session_routing_defaults() -> dict[str, Any]:
    """Return default ``session-routing`` settings."""

    return copy.deepcopy(_SESSION_ROUTING_DEFAULTS)


def default_project_capability_settings(
    conn: Any | None = None,
    project_id: int | None = None,
    *,
    base_branch: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return every out-of-the-box project policy capability."""

    return {
        PROJECT_POLICY_CAPABILITY: project_policy_defaults(
            conn, project_id, base_branch=base_branch,
        ),
        SESSION_ROUTING_CAPABILITY: session_routing_defaults(),
    }


def load_project_policy_settings(
    conn: Any,
    project_id: int | None,
) -> dict[str, Any]:
    """Read the canonical ``project-policy`` capability settings."""

    if project_id is None:
        return {}
    return _read_capability_settings(
        conn, int(project_id), PROJECT_POLICY_CAPABILITY,
    )


def project_policy_value(
    conn: Any,
    project_id: int | None,
    key: str,
    default: Any = None,
) -> Any:
    """Read one DB-owned project policy key."""

    settings = load_project_policy_settings(conn, project_id)
    value = settings.get(key)
    return default if value in (None, "") else value


def set_project_policy_value(
    conn: Any,
    project_id: int,
    key: str,
    value: Any,
) -> None:
    """Set one ``project-policy`` key after ensuring the capability exists."""

    ensure_default_policy_capabilities(conn, int(project_id))
    current = _read_capability_settings(
        conn, int(project_id), PROJECT_POLICY_CAPABILITY,
    )
    current[str(key)] = value
    conn.execute(
        f"UPDATE project_capabilities SET settings={_p(conn)} "
        f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (_settings_json(current), int(project_id), PROJECT_POLICY_CAPABILITY),
    )


def ensure_default_policy_capabilities(
    conn: Any,
    project_ids: int | Sequence[int] | None = None,
    *,
    base_branch: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Create or repair default capability rows without clobbering edits.

    Existing rows are deep-merged: missing default keys are added, but present
    values are preserved.  The caller owns commit/rollback.
    """

    project_id_list = _project_ids(conn, project_ids)
    report: dict[str, dict[str, Any]] = {}
    for project_id in project_id_list:
        per_project: list[CapabilityRepairResult] = []
        defaults_by_capability = default_project_capability_settings(
            conn, project_id, base_branch=base_branch,
        )
        for cap_type, defaults in defaults_by_capability.items():
            per_project.append(
                _ensure_capability_settings(conn, project_id, cap_type, defaults)
            )
        report[str(project_id)] = {
            result.capability: result.as_dict() for result in per_project
        }
    return report


def _project_ids(conn: Any, project_ids: int | Sequence[int] | None) -> list[int]:
    if project_ids is None:
        rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
        return [int(row_value(row, "id", 0)) for row in rows]
    if isinstance(project_ids, int):
        return [project_ids]
    return [int(project_id) for project_id in project_ids]


def _ensure_capability_settings(
    conn: Any,
    project_id: int,
    cap_type: str,
    defaults: Mapping[str, Any],
) -> CapabilityRepairResult:
    row = conn.execute(
        "SELECT settings FROM project_capabilities "
        f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (project_id, cap_type),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)})",
            (
                project_id,
                cap_type,
                _settings_json(defaults),
                iso8601_now(),
            ),
        )
        return CapabilityRepairResult(
            capability=cap_type,
            created=True,
            repaired_keys=tuple(defaults.keys()),
        )

    current = _loads_settings(row_value(row, "settings", 0))
    merged = copy.deepcopy(current)
    repaired: list[str] = []
    _merge_missing(merged, defaults, repaired, prefix="")
    if repaired:
        conn.execute(
            f"UPDATE project_capabilities SET settings={_p(conn)} "
            f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
            (_settings_json(merged), project_id, cap_type),
        )
    return CapabilityRepairResult(
        capability=cap_type,
        created=False,
        repaired_keys=tuple(repaired),
    )


def _read_capability_settings(
    conn: Any,
    project_id: int,
    cap_type: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (project_id, cap_type),
    ).fetchone()
    if row is None:
        return {}
    return _loads_settings(row_value(row, "settings", 0))


def _loads_settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _merge_missing(
    current: MutableMapping[str, Any],
    defaults: Mapping[str, Any],
    repaired: list[str],
    *,
    prefix: str,
) -> None:
    for key, value in defaults.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in current:
            current[key] = copy.deepcopy(value)
            repaired.append(path)
            continue
        if isinstance(current[key], MutableMapping) and isinstance(value, Mapping):
            _merge_missing(current[key], value, repaired, prefix=path)


def _settings_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


__all__ = [
    "CapabilityRepairResult",
    "PROJECT_POLICY_CAPABILITY",
    "SESSION_ROUTING_CAPABILITY",
    "default_project_capability_settings",
    "ensure_default_policy_capabilities",
    "load_project_policy_settings",
    "project_policy_defaults",
    "project_policy_value",
    "session_routing_defaults",
    "set_project_policy_value",
]
