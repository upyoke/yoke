"""Implementing → reviewing-implementation evidence gate.

Owns :func:`check_implementing_to_reviewing_implementation_gate` — the
evidence gate the advance preflight executes inline before allowing the
``implementing → reviewing-implementation`` transition.

for each identifier in ``profile.migration_modules``:

* ``apply`` — require the module in the ordered history and a passing
  rehearsal receipt for it on this control plane.
* ``retire`` — require a decision record at
  ``docs/archive/decisions/<module>.md`` with
  ``retired-without-apply: true`` frontmatter that names the module
  and the model.

Rehearsal receipts are item evidence and live on the control plane that
holds the item; :mod:`yoke_core.domain.migration_rehearsal_evidence` owns that
location for the rehearsal that writes them and for this gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.db_mutation_gate_loaders import (
    ItemIdRefMismatch,
    _load_capability_settings,
    _load_item_row,
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
from yoke_core.domain.migration_rehearsal_evidence import module_rehearsed


def check_implementing_to_reviewing_implementation_gate(
    item_id: int,
    *,
    conn: Optional[Any] = None,
) -> GateOutcome:
    """Evidence gate for the ``implementing → reviewing-implementation`` transition.

    For each identifier in ``profile.migration_modules``:
      * ``apply`` → require the module in the ordered history and a passing
        rehearsal receipt for it on this control plane.
      * ``retire`` → require a decision record at
        ``docs/archive/decisions/<module>.md`` with
        ``retired-without-apply: true`` frontmatter that names the module
        and the model.
    """

    def _evaluate(c: Any) -> GateOutcome:
        try:
            item = _load_item_row(c, item_id)
        except ItemIdRefMismatch as exc:
            return GateOutcome(passed=False, errors=[str(exc)])
        if item is None:
            from yoke_core.domain.project_identity import render_item_ref

            return GateOutcome(
                passed=False,
                errors=[f"Item {render_item_ref(c, item_id)} not found"],
            )

        parsed = _safe_parse_dict(item.get("db_mutation_profile"))
        try:
            profile = validate_profile(parsed) if parsed else {"state": STATE_NONE}
        except DbMutationProfileError as exc:
            return GateOutcome(
                passed=False, errors=[f"db_mutation_profile invalid: {exc}"]
            )

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
        lane_path = _item_lane_path(c, item_id)

        if intent == MUTATION_INTENT_APPLY:
            from yoke_core.domain.project_identity import render_item_ref

            item_ref = render_item_ref(c, item_id)
            for identifier in identifiers:
                missing = _history_membership_error(lane_path, model, identifier)
                if missing is not None:
                    errors.append(missing)
                    continue
                if not module_rehearsed(
                    c,
                    project_id=project_id,
                    model_name=profile["model_name"],
                    identifier=identifier,
                ):
                    errors.append(
                        f"module '{identifier}': no passing rehearsal receipt "
                        f"for model '{profile['model_name']}' of project "
                        f"'{project}' on this control plane. Remediation: run "
                        f"`yoke migration rehearse {item_ref}` under the "
                        "direct authority that holds this item; it applies "
                        "the module to the model's validation surface and "
                        "records the receipt this gate reads."
                    )
            return GateOutcome(passed=not errors, errors=errors)

        return GateOutcome(
            passed=False,
            errors=[f"unhandled mutation_intent '{intent}'"],
        )

    if conn is not None:
        return _evaluate(conn)
    with db_helpers.connect() as owned:
        return _evaluate(owned)


def _item_lane_path(conn: Any, item_id: int) -> Optional[Path]:
    """The item's own lane on this machine, or ``None`` where none is mapped.

    The entry under review is authored in the item's lane and reaches the
    project's default branch only when the item merges, so the project
    checkout never holds it at this gate.
    """
    from yoke_core.domain.project_checkout_locations import item_worktree_path

    lane = item_worktree_path(conn, item_id)
    return lane if lane is not None and lane.is_dir() else None


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
        # A process with no lane for the item (the hosted server) cannot read
        # the history directory at all.
        # That is "cannot inspect", not "the module is missing", so it does not
        # manufacture a failure -- the rehearsal receipt, which this gate still
        # requires, is evidence the module existed and ran somewhere.
        return None
    try:
        entries = ordered_entries(Path(repo_path) / modules_rel)
    except HistoryError as exc:
        return f"module '{identifier}': migration history is malformed: {exc}"

    match = next(
        (
            e
            for e in entries
            if e.name == identifier or e.name.endswith(f"_{identifier}")
        ),
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
    "_history_membership_error",
    "check_implementing_to_reviewing_implementation_gate",
]
