"""Teaching-audit records and inventory projections for CLI and module recipes."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Iterable, Sequence

from yoke_cli import operation_inventory as ops
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY, SUBCOMMAND_ALIAS_REGISTRY
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

DRIFT_UNRESOLVED_YOKE = "taught_yoke_command_unresolved"
DRIFT_UNSANCTIONED_INTERNAL = "taught_internal_module_unsanctioned"
DRIFT_MISSING_REGISTERED = "registered_command_missing_from_teaching"
DRIFT_MISSING_TOOL_SHAPED = "tool_shaped_command_missing_from_teaching"
DRIFT_STALE_ARGUMENT_SHAPE = "stale_argument_shape"


@dataclass(frozen=True)
class TaughtSurface:
    source: str
    line_number: int
    recipe: str
    kind: str
    command_form: str
    resolution: str
    function_id: str | None = None
    status: str | None = None
    reason: str | None = None
    drift_type: str | None = None
    smoke_error: str | None = None


@dataclass(frozen=True)
class MissingTeaching:
    command_form: str
    source_kind: str
    function_id: str | None
    drift_type: str


@dataclass(frozen=True)
class TeachingAudit:
    surfaces: tuple[TaughtSurface, ...]
    missing: tuple[MissingTeaching, ...]

    @property
    def drift_count(self) -> int:
        return sum(1 for row in self.surfaces if row.drift_type) + len(self.missing)


def _resolve_python_recipe(source: str, line_number: int, recipe: str) -> TaughtSurface:
    recipe_tokens = _split_or_empty(recipe)
    best: ops.OperationEntry | None = None
    for entry in ops.all_entries():
        if not entry.shell_form.startswith("python"):
            continue
        entry_tokens = _split_or_empty(entry.shell_form)
        if recipe_tokens[: len(entry_tokens)] == entry_tokens:
            if best is None or len(entry_tokens) > len(
                _split_or_empty(best.shell_form)
            ):
                best = entry
    if best and best.status == ops.PERMANENT:
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "python_module",
            best.shell_form,
            "permanent",
            status=best.status,
            reason=best.reason,
        )
    return TaughtSurface(
        source,
        line_number,
        recipe,
        "python_module",
        best.shell_form if best else _python_module_form(recipe_tokens),
        best.status if best else "unresolved",
        status=best.status if best else None,
        reason=best.reason if best else None,
        drift_type=DRIFT_UNSANCTIONED_INTERNAL,
    )


def _split_or_empty(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        return []


def _python_module_form(tokens: Sequence[str]) -> str:
    return " ".join(tokens[:3]) if len(tokens) >= 3 else " ".join(tokens)


def _missing_teaching_rows(taught_forms: set[str]) -> Iterable[MissingTeaching]:
    registry_forms = {
        "yoke " + " ".join(tokens): (function_id, False)
        for tokens, (function_id, _adapter) in SUBCOMMAND_REGISTRY.items()
    }
    registry_forms.update(
        {
            "yoke " + " ".join(tokens): (function_id, True)
            for tokens, (function_id, _adapter) in SUBCOMMAND_ALIAS_REGISTRY.items()
        }
    )
    for command_form, (function_id, is_alias) in registry_forms.items():
        if command_form not in taught_forms:
            yield MissingTeaching(
                command_form,
                "alias" if is_alias else "registered",
                function_id,
                DRIFT_MISSING_REGISTERED,
            )
    for tokens in TOOL_SHAPED_SUBCOMMANDS:
        command_form = "yoke " + " ".join(tokens)
        if command_form not in taught_forms:
            yield MissingTeaching(
                command_form, "tool_shaped", None, DRIFT_MISSING_TOOL_SHAPED
            )
