"""Implementing → reviewing-implementation evidence gate.

Owns :func:`check_implementing_to_reviewing_implementation_gate` — the
evidence gate the advance preflight executes inline before allowing the
``implementing → reviewing-implementation`` transition.

for each identifier in ``profile.migration_modules``:

* ``apply`` — require a ``migration_audit`` row with ``state='completed'``
  on the model's authoritative DB for the configured runner.
* ``retire`` — require a decision record at
  ``docs/archive/decisions/<module>.md`` with
  ``retired-without-apply: true`` frontmatter that names the module
  and the model.

The authoritative DB the audit row check reads is declared by the
project's ``migration_model`` capability (``authoritative_db.location``);
the worktree's validation surface is **not** sufficient.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.db_mutation_gate_evidence import (
    _audit_row_completed_for_module,
    _verify_retire_record,
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
    MUTATION_INTENT_RETIRE,
    STATE_NONE,
    DbMutationProfileError,
    validate as validate_profile,
)
from yoke_core.domain.migration_model_capability import resolve_model


CONNECTED_POSTGRES_AUDIT_TOKEN = "<connected-postgres>"


def check_implementing_to_reviewing_implementation_gate(
    item_id: int,
    *,
    conn: Optional[Any] = None,
    audit_db_path: Optional[str] = None,
) -> GateOutcome:
    """Evidence gate for the ``implementing → reviewing-implementation`` transition.

    For each identifier in ``profile.migration_modules``:
      * ``apply`` → require an audit row with ``state='completed'`` on the
        model's authoritative DB for the configured runner.
      * ``retire`` → require a decision record at
        ``docs/archive/decisions/<module>.md`` with
        ``retired-without-apply: true`` frontmatter that names the module
        and the model.

    *audit_db_path* lets tests point the audit-row check at a specific
    DB; production callers leave it ``None`` and the helper resolves the
    audit DB from the model's authoritative-db location.
    """

    def _evaluate(c: Any) -> GateOutcome:
        item = _load_item_row(c, item_id)
        if item is None:
            return GateOutcome(passed=False, errors=[f"Item YOK-{item_id} not found"])

        parsed = _safe_parse_dict(item.get("db_mutation_profile"))
        try:
            profile = validate_profile(parsed) if parsed else {"state": STATE_NONE}
        except DbMutationProfileError as exc:
            return GateOutcome(passed=False, errors=[f"db_mutation_profile invalid: {exc}"])

        if profile["state"] == STATE_NONE:
            return GateOutcome(passed=True)

        project = item.get("project") or ""
        project_id = int(item["project_id"])
        capability_settings = _load_capability_settings(c, project)
        if capability_settings is None:
            return GateOutcome(
                passed=False,
                errors=[
                    f"project '{project}' has no valid migration_model "
                    "capability; cannot verify evidence"
                ],
            )
        try:
            model = resolve_model(capability_settings, profile["model_name"])
        except KeyError:
            return GateOutcome(
                passed=False,
                errors=[
                    f"db_mutation_profile.model_name '{profile['model_name']}' "
                    f"is not declared in project '{project}'"
                ],
            )

        repo_path = _resolve_repo_path(c, project)
        if repo_path is None:
            return GateOutcome(
                passed=False,
                errors=[
                    f"project '{project}' has no machine-local checkout mapping; "
                    "cannot verify retire decision records"
                ],
            )

        errors: List[str] = []
        intent = profile["mutation_intent"]
        identifiers: List[str] = list(profile["migration_modules"])

        if intent == MUTATION_INTENT_RETIRE:
            for identifier in identifiers:
                ok, reason = _verify_retire_record(
                    repo_path, identifier, profile["model_name"]
                )
                if not ok:
                    errors.append(f"module '{identifier}': {reason}")
            return GateOutcome(passed=not errors, errors=errors)

        if intent == MUTATION_INTENT_APPLY:
            audit_path = audit_db_path or _resolve_audit_db_path(
                repo_path, model
            )
            if audit_path is None:
                return GateOutcome(
                    passed=False,
                    errors=[
                        f"cannot resolve authoritative DB for model "
                        f"'{profile['model_name']}'; evidence gate cannot read "
                        "migration_audit"
                    ],
                )
            audit_conn = db_helpers.connect(audit_path)
            try:
                for identifier in identifiers:
                    if not _audit_row_completed_for_module(
                        audit_conn, project_id, profile["model_name"], identifier,
                    ):
                        errors.append(
                            f"module '{identifier}': no migration_audit row "
                            f"with state='completed' found on {audit_path}. "
                            f"Remediation: run the configured migration apply "
                            f"lifecycle hook against the configured Postgres "
                            f"authority, then record the completed audit row. See "
                            f".agents/skills/yoke/advance/implementing/"
                            f"test-and-record.md section a4."
                        )
                # Post-state verification for destructive schema claims.
                # A completed migration_audit row alone is insufficient — the
                # authoritative DB's current shape must also match the claim.
                # This closes the failure mode where stale init/bootstrap
                # code or ambient auto-init re-adds a retired column after
                # the cutover has officially completed.
                if not errors:
                    post_state_errors = _verify_destructive_post_state(
                        audit_conn,
                        project=project,
                        profile=profile,
                        repo_path=repo_path,
                        audit_path=audit_path,
                    )
                    errors.extend(post_state_errors)
            finally:
                audit_conn.close()
            return GateOutcome(passed=not errors, errors=errors)

        return GateOutcome(
            passed=False,
            errors=[f"unhandled mutation_intent '{intent}'"],
        )

    if conn is not None:
        return _evaluate(conn)
    with db_helpers.connect() as owned:
        return _evaluate(owned)


def _resolve_audit_db_path(
    repo_path: Path, model: Mapping[str, Any]
) -> Optional[str]:
    auth = model.get("authoritative_db") or {}
    if auth.get("kind") != "sqlite_file":
        return CONNECTED_POSTGRES_AUDIT_TOKEN
    location = auth.get("location") or {}
    rel = location.get("path")
    if not rel:
        return None
    candidate = (repo_path / rel).resolve()
    return str(candidate)


def _verify_destructive_post_state(
    audit_conn: Any,
    *,
    project: str,
    profile: Mapping[str, Any],
    repo_path: Optional[Path],
    audit_path: str,
) -> List[str]:
    """Post-state verification for destructive schema claims."""
    from yoke_core.domain.db_mutation_post_state import (
        verify_destructive_post_state,
    )

    return verify_destructive_post_state(
        audit_conn,
        project=project,
        profile=profile,
        repo_path=repo_path,
        audit_path=audit_path,
    )


__all__ = [
    "_resolve_audit_db_path",
    "_verify_destructive_post_state",
    "check_implementing_to_reviewing_implementation_gate",
]
