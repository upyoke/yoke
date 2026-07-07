"""Polishing-implementation → implemented thin verification gate.

Owns :func:`check_polishing_implementation_to_implemented_gate` — the
post-implementation verification step.

Re-runs the implementing-phase evidence check, then (for ``apply``)
confirms the rollback backup file referenced on the audit row is still
present AND no audit row points at the module in an in-progress state
(``state IN {backup_created, live_applied}``).  Verification only —
never applies anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import command_definitions, db_backend, db_helpers
from yoke_core.domain.db_mutation_gate_implementing import (
    _resolve_audit_db_path,
    check_implementing_to_reviewing_implementation_gate,
)
from yoke_core.domain.db_mutation_gate_loaders import (
    _load_capability_settings,
    _load_item_row,
    _resolve_repo_path,
)
from yoke_core.domain.db_mutation_gate_shared import (
    GateOutcome,
    _safe_parse_dict,
)
from yoke_core.domain.db_mutation_profile import (
    MUTATION_INTENT_APPLY,
    STATE_NONE,
    validate as validate_profile,
)
from yoke_core.domain.item_test_results_classify import classify_test_results
from yoke_core.domain.migration_model_capability import resolve_model


def check_polishing_implementation_to_implemented_gate(
    item_id: int,
    *,
    conn: Optional[Any] = None,
    audit_db_path: Optional[str] = None,
) -> GateOutcome:
    """Thin post-implementation verification.

    Re-runs the implementing-phase evidence check, then (for ``apply``)
    confirms the rollback backup file referenced on the audit row is
    still present AND no audit row points at this module in an
    in-progress state (``state IN {backup_created, live_applied}``).
    Verification only — never applies anything.
    """
    base = check_implementing_to_reviewing_implementation_gate(
        item_id, conn=conn, audit_db_path=audit_db_path,
    )
    if not base.passed:
        return base

    def _evaluate(c: Any) -> GateOutcome:
        item = _load_item_row(c, item_id)
        if item is None:
            return GateOutcome(passed=False, errors=[f"Item YOK-{item_id} not found"])

        test_results_error = _check_test_results_evidence(item)

        profile = validate_profile(_safe_parse_dict(item.get("db_mutation_profile")))
        if profile["state"] == STATE_NONE:
            if test_results_error:
                return GateOutcome(passed=False, errors=[test_results_error])
            return GateOutcome(passed=True)
        if profile["mutation_intent"] != MUTATION_INTENT_APPLY:
            if test_results_error:
                return GateOutcome(passed=False, errors=[test_results_error])
            return GateOutcome(passed=True)

        project = item.get("project") or ""
        project_id = int(item["project_id"])
        capability_settings = _load_capability_settings(c, project)
        if capability_settings is None:
            return GateOutcome(passed=True)  # base gate already failed if missing
        model = resolve_model(capability_settings, profile["model_name"])
        repo_path = _resolve_repo_path(c, project)
        audit_path = audit_db_path or _resolve_audit_db_path(repo_path, model)
        if audit_path is None:
            return GateOutcome(passed=True)

        errors: List[str] = []
        audit_conn = db_helpers.connect(audit_path)
        try:
            p = "%s" if db_backend.connection_is_postgres(audit_conn) else "?"
            for identifier in profile["migration_modules"]:
                rows = audit_conn.execute(
                    "SELECT state, backup_path FROM migration_audit "
                    f"WHERE migration_name = {p} "
                    f"AND project_id = {p} "
                    f"AND COALESCE(model_name, {p}) = {p} "
                    "AND state IN "
                    "('backup_created', 'live_applied') "
                    "ORDER BY id DESC LIMIT 1",
                    (identifier, project_id, profile["model_name"], profile["model_name"]),
                ).fetchall()
                if rows:
                    errors.append(
                        f"module '{identifier}' has stale in-progress audit row "
                        f"({rows[0]['state'] if hasattr(rows[0], 'keys') else rows[0][0]}) "
                        "— resolve before advancing past polishing"
                    )
                    continue
                backup_row = audit_conn.execute(
                    "SELECT backup_path FROM migration_audit "
                    f"WHERE migration_name = {p} "
                    f"AND project_id = {p} "
                    f"AND COALESCE(model_name, {p}) = {p} "
                    "AND state = 'completed' "
                    "ORDER BY id DESC LIMIT 1",
                    (identifier, project_id, profile["model_name"], profile["model_name"]),
                ).fetchone()
                if backup_row is None:
                    continue
                backup_path = backup_row["backup_path"] if hasattr(backup_row, "keys") else backup_row[0]
                if backup_path:
                    candidate = Path(backup_path)
                    if not candidate.is_absolute():
                        candidate = repo_path / candidate
                    if not candidate.is_file():
                        errors.append(
                            f"module '{identifier}' rollback backup missing at "
                            f"{candidate}"
                        )
        finally:
            audit_conn.close()

        if test_results_error:
            errors.append(test_results_error)
        return GateOutcome(passed=not errors, errors=errors)

    if conn is not None:
        return _evaluate(conn)
    with db_helpers.connect() as owned:
        return _evaluate(owned)


def _check_test_results_evidence(item: dict) -> Optional[str]:
    """Symmetric upstream half of the merge-engine verification gate.

    Polish doctrine (`.agents/skills/yoke/polish/verify-and-commit.md`)
    requires polish to capture passing pytest output into
    ``items.test_results`` before advancing past
    ``polishing-implementation``. The merge engine's
    ``MergeBlockedNoVerificationEvidence`` path then substitutes that
    capture when no required CI checks are configured. Catching the
    empty/failed verdict at polish-time fails fast in the same session
    that ran the tests, instead of letting an unverified item reach
    usher hours later.

    Project-agnostic filter: enforces only when the item's project has a
    ``command_definitions.quick`` command configured. Projects without
    a registered quick command (the legacy carve-out) pass through
    without inspection so the gate doesn't block work on projects that
    have no pytest runner wired up yet.

    Returns ``None`` when the gate is satisfied, otherwise the error
    string to surface.
    """
    project = item.get("project") or ""
    if not project:
        return None
    if not command_definitions.get_command(project, "quick"):
        return None
    raw = item.get("test_results") or ""
    verdict = classify_test_results(raw)
    if verdict == "passed":
        return None
    if verdict == "failed":
        return (
            "items.test_results carries a failure verdict — polish must "
            "fix the failing tests and re-capture a passing pytest run "
            "before advancing past polishing-implementation. Re-run the "
            "project's quick command (see `command_definitions.quick`) "
            "and write the capture via the `items.structured_field.replace` "
            "function call with `payload.field=\"test_results\"` "
            "(see `.agents/skills/yoke/polish/verify-and-commit.md`)."
        )
    return (
        "items.test_results is empty — polish must capture a passing "
        "pytest verdict before advancing past polishing-implementation. "
        "Run the project's quick command (see `command_definitions.quick`) "
        "and write the capture via the `items.structured_field.replace` "
        "function call with `payload.field=\"test_results\"` "
        "(see `.agents/skills/yoke/polish/verify-and-commit.md`)."
    )


__all__ = ["check_polishing_implementation_to_implemented_gate"]
