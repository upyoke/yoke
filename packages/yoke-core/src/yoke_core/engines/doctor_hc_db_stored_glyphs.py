"""HC-stored-glyph-contract: every stored glyph obeys the glyph contract.

The board renders stored glyphs inside fixed-width columns — a project's
``{emoji} {slug}`` label, a workflow stage's status glyph, a session row's
level glyph — so one value that breaks the contract in
:mod:`yoke_contracts.glyph_contract` shears every row beneath it. The
writers refuse such a value, but a value stored before its writer checked
is still served to every surface. This check reads every stored glyph and
FAILs on each violation, naming where it lives and the registered command
that corrects it.

Scope:

* ``projects.emoji`` — corrected with ``yoke projects update``.
* ``level_metadata.<LEVEL>.glyph`` in each project's ``session-routing``
  capability settings — corrected with
  ``yoke projects capability-settings merge``.
* ``stages[].glyph`` in every stored workflow version — corrected by
  publishing a version whose stage carries a contract-safe glyph through the
  workflow's own source (the code-owned fixture for a built-in, the owning
  Pack otherwise), then moving pinned items with ``yoke workflows item
  migrate``.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Iterable

from yoke_contracts.glyph_contract import SAFE_GLYPH_EXAMPLES, glyph_contract_error
from yoke_core.domain.db_helpers import query_rows
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _table_exists,
)

HC_SLUG = "HC-stored-glyph-contract"
HC_NAME = "Stored glyphs obey the glyph contract"
_MAX_REPORTED = 40


def _load_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None


def project_emoji_violations(conn) -> list[str]:
    """Report each non-empty ``projects.emoji`` the contract refuses."""
    rows = query_rows(
        conn,
        "SELECT slug, name, emoji FROM projects "
        "WHERE emoji IS NOT NULL AND emoji <> '' ORDER BY id",
    )
    violations: list[str] = []
    for row in rows:
        reason = glyph_contract_error(row["emoji"])
        if reason is None:
            continue
        violations.append(
            f"projects.emoji for project {row['slug']} ({row['emoji']!r}) "
            f"{reason}. Correct with: yoke projects update --slug "
            f"{shlex.quote(str(row['slug']))} --name "
            f"{shlex.quote(str(row['name']))} --emoji <glyph>"
        )
    return violations


def level_glyph_violations(conn) -> list[str]:
    """Report each ``session-routing`` level glyph the contract refuses."""
    rows = query_rows(
        conn,
        "SELECT p.slug, c.settings FROM project_capabilities c "
        "JOIN projects p ON p.id = c.project_id "
        "WHERE c.type = 'session-routing' ORDER BY p.id",
    )
    violations: list[str] = []
    for row in rows:
        settings = _load_json(row["settings"])
        metadata = (
            settings.get("level_metadata") if isinstance(settings, dict) else None
        )
        if not isinstance(metadata, dict):
            continue
        for level, entry in sorted(metadata.items()):
            if not isinstance(entry, dict) or "glyph" not in entry:
                continue
            reason = glyph_contract_error(entry["glyph"])
            if reason is None:
                continue
            violations.append(
                f"level_metadata.{level}.glyph in project {row['slug']} "
                f"session-routing settings ({entry['glyph']!r}) {reason}. "
                "Correct with: yoke projects capability-settings merge "
                f"--project {shlex.quote(str(row['slug']))} --cap-type "
                f"session-routing --set level_metadata.{level}.glyph=<glyph>"
            )
    return violations


def _workflow_correction(workflow_id: str, source: str) -> str:
    if source == "built_in":
        return (
            "give the stage a contract-safe glyph in the built-in fixture, "
            f"then run: yoke workflows canon-update apply {workflow_id} "
            "--expected-current-version N"
        )
    return (
        "publish a new version of the owning Pack with a contract-safe stage "
        "glyph, then run: yoke packs update PACK --project P --apply"
    )


def workflow_stage_glyph_violations(conn) -> list[str]:
    """Report each stored workflow stage glyph the contract refuses."""
    rows = query_rows(
        conn,
        "SELECT w.id, w.source, v.version, v.definition_json "
        "FROM workflow_versions v JOIN workflows w ON w.id = v.workflow_id "
        "ORDER BY w.id, v.version",
    )
    violations: list[str] = []
    for row in rows:
        definition = _load_json(row["definition_json"])
        stages: Iterable[Any] = (
            definition.get("stages") or [] if isinstance(definition, dict) else []
        )
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict) or "glyph" not in stage:
                continue
            reason = glyph_contract_error(stage["glyph"])
            if reason is None:
                continue
            violations.append(
                f"workflow {row['id']} v{row['version']} "
                f"stages[{index}].glyph ({stage.get('id')}: {stage['glyph']!r}) "
                f"{reason}. Correct: "
                f"{_workflow_correction(str(row['id']), str(row['source']))}; "
                "move pinned items with: yoke workflows item migrate ITEM"
            )
    return violations


def stored_glyph_violations(conn) -> list[str]:
    """Every stored glyph violation, in projects → levels → workflows order."""
    violations: list[str] = []
    if _table_exists(conn, "projects"):
        violations += project_emoji_violations(conn)
        if _table_exists(conn, "project_capabilities"):
            violations += level_glyph_violations(conn)
    if _table_exists(conn, "workflow_versions") and _table_exists(conn, "workflows"):
        violations += workflow_stage_glyph_violations(conn)
    return violations


def hc_stored_glyph_contract(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stored-glyph-contract: FAIL on every stored glyph the contract refuses."""
    violations = stored_glyph_violations(conn)
    if not violations:
        rec.record(HC_SLUG, HC_NAME, "PASS", "")
        return
    shown = violations[:_MAX_REPORTED]
    lines = [f"- {line}" for line in shown]
    if len(violations) > len(shown):
        lines.append(f"- … and {len(violations) - len(shown)} more")
    lines.append("Contract-safe glyphs include " + " ".join(SAFE_GLYPH_EXAMPLES) + ".")
    rec.record(
        HC_SLUG,
        HC_NAME,
        "FAIL",
        f"{len(violations)} stored glyph(s) break the glyph contract:\n"
        + "\n".join(lines),
    )


__all__ = [
    "HC_NAME",
    "HC_SLUG",
    "hc_stored_glyph_contract",
    "level_glyph_violations",
    "project_emoji_violations",
    "stored_glyph_violations",
    "workflow_stage_glyph_violations",
]
