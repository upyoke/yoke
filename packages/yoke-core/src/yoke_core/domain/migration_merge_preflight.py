"""Merge-time gate for numbered governed migration entries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from yoke_core.domain.db_mutation_gate_shared import (
    _NON_TERMINAL_STATUSES,
    _safe_parse_dict,
)
from yoke_core.domain.db_mutation_profile import (
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    DbMutationProfileError,
    validate as validate_profile,
)
from yoke_core.domain.migration_history import HistoryError
from yoke_core.domain.migration_history_integration import (
    migration_ordinal,
    require_merge_history_extension,
)
from yoke_core.domain.migration_model_capability import (
    MigrationModelCapabilityError,
    validate as validate_capability,
)
from yoke_core.domain.migration_model_capability_defaults import resolve_model


@dataclass(frozen=True)
class MigrationMergeGate:
    applicable: bool
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors


def _profile(raw: Any) -> Mapping[str, Any] | None:
    parsed = _safe_parse_dict(raw)
    if parsed.get("state") != STATE_DECLARED:
        return None
    try:
        return validate_profile(parsed)
    except DbMutationProfileError:
        return None


def _numbered_modules(profile: Mapping[str, Any]) -> dict[int, str]:
    numbered: dict[int, str] = {}
    for identifier in profile.get("migration_modules") or ():
        ordinal = migration_ordinal(str(identifier))
        if ordinal is None:
            continue
        if ordinal in numbered:
            raise HistoryError(
                f"db_mutation_profile declares duplicate migration ordinal "
                f"{ordinal}: {numbered[ordinal]!r} and {identifier!r}"
            )
        numbered[ordinal] = str(identifier)
    return numbered


def _modules_dir(settings_json: str, model_name: str) -> str:
    try:
        raw = json.loads(settings_json)
        capability = validate_capability(raw)
        model = resolve_model(capability, model_name)
        config = (model.get("runner") or {}).get("config") or {}
        value = str(config.get("modules_dir") or "")
    except (
        json.JSONDecodeError,
        KeyError,
        MigrationModelCapabilityError,
        TypeError,
    ) as exc:
        raise HistoryError(
            f"migration_model capability cannot resolve model {model_name!r}: {exc}"
        ) from exc
    if not value:
        raise HistoryError(
            f"migration_model capability model {model_name!r} has no modules_dir"
        )
    return value


def _collision_errors(
    rows: Iterable[Mapping[str, Any]],
    *,
    item_id: int,
    capability_settings_json: str,
    current_modules_dir: str,
    current: Mapping[int, str],
) -> list[str]:
    errors: list[str] = []
    for row in rows:
        try:
            other_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if other_id == item_id or str(row.get("status") or "") not in _NON_TERMINAL_STATUSES:
            continue
        other = _profile(row.get("db_mutation_profile"))
        if other is None:
            continue
        try:
            other_modules_dir = _modules_dir(
                capability_settings_json, str(other["model_name"])
            )
        except HistoryError as exc:
            errors.append(f"item {other_id} cannot resolve migration history: {exc}")
            continue
        if other_modules_dir != current_modules_dir:
            continue
        try:
            other_numbered = _numbered_modules(other)
        except HistoryError as exc:
            errors.append(f"item {other_id} has malformed migration ordering: {exc}")
            continue
        for ordinal in sorted(current.keys() & other_numbered.keys()):
            errors.append(
                f"item {other_id} is non-terminal and also holds migration "
                f"ordinal {ordinal}: {other_numbered[ordinal]!r} conflicts "
                f"with {current[ordinal]!r}"
            )
    return errors


def migration_merge_applicable(
    rows: Iterable[Mapping[str, Any]], item_id: int,
) -> bool:
    """Whether *item_id* declares at least one numbered apply module."""
    current_row = next(
        (row for row in rows if str(row.get("id") or "") == str(item_id)),
        None,
    )
    profile = _profile(
        current_row.get("db_mutation_profile") if current_row is not None else None
    )
    return bool(
        profile is not None
        and profile.get("mutation_intent") == MUTATION_INTENT_APPLY
        and any(
            migration_ordinal(str(name)) is not None
            for name in profile.get("migration_modules") or ()
        )
    )


def evaluate_migration_merge(
    *,
    rows: Iterable[Mapping[str, Any]],
    item_id: int,
    capability_settings_json: str,
    worktree_path: Path,
    integration_target: str,
) -> MigrationMergeGate:
    """Evaluate history extension, next-ordinal, and live-item collisions."""
    materialized = tuple(rows)
    current_row = next(
        (row for row in materialized if str(row.get("id") or "") == str(item_id)),
        None,
    )
    if current_row is None:
        return MigrationMergeGate(True, (f"item {item_id} is absent from items.list",))
    current_profile = _profile(current_row.get("db_mutation_profile"))
    if (
        current_profile is None
        or current_profile.get("mutation_intent") != MUTATION_INTENT_APPLY
    ):
        return MigrationMergeGate(False)
    try:
        numbered = _numbered_modules(current_profile)
    except HistoryError as exc:
        return MigrationMergeGate(True, (str(exc),))
    if not numbered:
        return MigrationMergeGate(False)
    try:
        modules_dir = _modules_dir(
            capability_settings_json,
            str(current_profile["model_name"]),
        )
    except HistoryError as exc:
        return MigrationMergeGate(True, (str(exc),))
    try:
        require_merge_history_extension(
            worktree_path=worktree_path,
            modules_dir=modules_dir,
            integration_target=integration_target,
            migration_modules=numbered.values(),
        )
    except HistoryError as exc:
        history_errors = [str(exc)]
    else:
        history_errors = []
    collision_errors = _collision_errors(
        materialized,
        item_id=item_id,
        capability_settings_json=capability_settings_json,
        current_modules_dir=modules_dir,
        current=numbered,
    )
    return MigrationMergeGate(True, tuple(history_errors + collision_errors))


__all__ = [
    "MigrationMergeGate",
    "evaluate_migration_merge",
    "migration_merge_applicable",
]
