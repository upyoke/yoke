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

from yoke_core.domain import db_helpers
from yoke_core.domain.db_mutation_gate_evidence import (
    _audit_row_rehearsed_for_module,
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

        errors: List[str] = []
        intent = profile["mutation_intent"]
        identifiers: List[str] = list(profile["migration_modules"])
        repo_path = _resolve_repo_path(c, project)

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
                    missing = _history_membership_error(
                        repo_path, model, identifier
                    )
                    if missing is not None:
                        errors.append(missing)
                        continue
                    if not _audit_row_rehearsed_for_module(
                        audit_conn, project_id, profile["model_name"], identifier,
                    ):
                        errors.append(
                            f"module '{identifier}': no rehearsal recorded in "
                            f"migration_audit on {audit_path}. Remediation: run "
                            f"`python3 -m yoke_core.domain.migration_apply "
                            f"rehearse <ITEM>`, which validates the module "
                            f"against the model's validation surface and records "
                            f"the receipt this gate reads."
                        )
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
    repo_path: Optional[Path], model: Mapping[str, Any]
) -> Optional[str]:
    auth = model.get("authoritative_db") or {}
    if auth.get("kind") != "sqlite_file":
        return CONNECTED_POSTGRES_AUDIT_TOKEN
    if repo_path is None:
        return None
    location = auth.get("location") or {}
    rel = location.get("path")
    if not rel:
        return None
    candidate = (repo_path / rel).resolve()
    return str(candidate)


def _history_membership_error(
    repo_path: Optional[Path], model: Mapping[str, Any], identifier: str
) -> Optional[str]:
    """Return why *identifier* is not a usable history entry, or ``None``.

    The evidence a migration is real is now that it is IN the ordered history
    and loadable, not that somebody already ran it. A module that is present,
    correctly named, and exposes ``apply(conn)`` will be applied by every
    install's boot converge; one that is absent or malformed will be applied
    by none, which is the failure this checks for.
    """
    from yoke_core.domain.migration_history import (
        HistoryError,
        load_migration_module,
        ordered_entries,
    )

    modules_rel = ((model.get("runner") or {}).get("config") or {}).get("modules_dir")
    if repo_path is None or not modules_rel:
        # A runner with no checkout cannot read the history directory at all.
        # That is "cannot inspect", not "the module is missing", so it does not
        # manufacture a failure -- the rehearsal receipt, which this gate still
        # requires, is evidence the module existed and ran somewhere.
        return None
    try:
        entries = ordered_entries(Path(repo_path) / modules_rel)
    except HistoryError as exc:
        return f"module '{identifier}': migration history is malformed: {exc}"

    match = next(
        (e for e in entries if e.name == identifier or e.name.endswith(f"_{identifier}")),
        None,
    )
    if match is None:
        return (
            f"module '{identifier}': not found in the ordered migration "
            f"history at {modules_rel}. Entries are named NNNN_slug.py and are "
            "permanent; an entry that is not in the history is applied by no "
            "install."
        )
    try:
        load_migration_module(match.path, match.name)
    except Exception as exc:  # noqa: BLE001 — surface the contract failure
        return f"module '{match.name}': does not load as a migration: {exc}"
    return None


__all__ = [
    "_resolve_audit_db_path",
    "_history_membership_error",
    "check_implementing_to_reviewing_implementation_gate",
]
