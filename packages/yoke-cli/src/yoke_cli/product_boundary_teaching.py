"""Taught recipe surface audit for the installable ``yoke`` CLI."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple

from yoke_cli import operation_inventory as ops
from yoke_cli.commands.registry import (
    SPACE_EXPANDED_ROUTE_REGISTRY,
    SUBCOMMAND_ALIAS_REGISTRY,
    SUBCOMMAND_REGISTRY,
    resolve,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS, resolve_tool_shaped
from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows
from yoke_cli.product_boundary_teaching_inventory import (
    DRIFT_UNRESOLVED_YOKE,
    DRIFT_UNSANCTIONED_INTERNAL,
    DRIFT_MISSING_REGISTERED,
    DRIFT_MISSING_TOOL_SHAPED,
    DRIFT_STALE_ARGUMENT_SHAPE,
    TaughtSurface,
    MissingTeaching,
    TeachingAudit,
    _resolve_python_recipe,
    _missing_teaching_rows,
)
from yoke_cli.product_boundary_teaching_sources import (
    TEACHING_GLOBS,
    command_path_is_template,
    help_usage_recipes,
)


SmokeRunner = Callable[[str], Tuple[bool, Optional[str], Optional[str]]]

_SKILL_ROUTER_ONLY = frozenset({"idea"})
_SMOKE_UNSAFE_PREFIXES = (
    "yoke board rebuild",
    "yoke strategy render",
    "yoke strategy ingest",
)

_PY_MODULE_RE = re.compile(r"^python3?\s+-m\s+yoke_core(?:\.[A-Za-z_]\w*)+")


def generate_teaching_audit(
    *,
    repo_root: Path | str,
    smoke_yoke: SmokeRunner | None = None,
    include_help: bool = False,
) -> TeachingAudit:
    root = Path(repo_root).resolve()
    extracted = tuple(_extract_surfaces(root, smoke_yoke=smoke_yoke))
    surfaces = extracted + (tuple(_help_usage_surfaces()) if include_help else ())
    taught_forms = {
        row.command_form
        for row in surfaces
        if row.kind == "yoke"
        and row.resolution
        in {
            "registered",
            "alias",
            "normalized",
            "tool_shaped",
        }
    }
    missing = tuple(
        sorted(
            _missing_teaching_rows(taught_forms),
            key=lambda r: (r.drift_type, r.command_form),
        )
    )
    return TeachingAudit(
        surfaces=tuple(
            sorted(surfaces, key=lambda r: (r.source, r.line_number, r.recipe))
        ),
        missing=missing,
    )


def _extract_surfaces(
    root: Path,
    *,
    smoke_yoke: SmokeRunner | None,
) -> Iterable[TaughtSurface]:
    for rel, line_number, recipe, standalone in extract_recipe_rows(
        root, TEACHING_GLOBS
    ):
        if recipe.startswith("yoke "):
            yield _resolve_yoke_recipe(
                rel, line_number, recipe, standalone, smoke_yoke=smoke_yoke
            )
        elif _PY_MODULE_RE.match(recipe):
            yield _resolve_python_recipe(rel, line_number, recipe)


def _resolve_yoke_recipe(
    source: str,
    line_number: int,
    recipe: str,
    standalone: bool,
    *,
    smoke_yoke: SmokeRunner | None,
) -> TaughtSurface:
    try:
        argv = shlex.split(recipe)
    except ValueError as exc:
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            recipe,
            "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE,
            smoke_error=str(exc),
        )
    if not argv or argv[0] != "yoke":
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            recipe,
            "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE,
        )
    command_argv, globals_ok = _strip_global_flags(argv[1:])
    if not globals_ok:
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            recipe,
            "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE,
        )
    if _top_level_command(command_argv):
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            recipe,
            "top_level",
        )
    try:
        tokens, function_id, _adapter, _remaining = resolve(command_argv)
        command_form = "yoke " + " ".join(tokens)
        resolution = (
            "alias"
            if tokens in SUBCOMMAND_ALIAS_REGISTRY
            else "normalized"
            if tokens in SPACE_EXPANDED_ROUTE_REGISTRY
            else "registered"
        )
        smoke_error = _smoke_error(recipe, standalone, smoke_yoke)
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            command_form,
            resolution,
            function_id=function_id,
            drift_type=DRIFT_STALE_ARGUMENT_SHAPE if smoke_error else None,
            smoke_error=smoke_error,
        )
    except KeyError:
        if not standalone and _registered_prefix(command_argv):
            return TaughtSurface(
                source,
                line_number,
                recipe,
                "yoke",
                recipe,
                "namespace_prefix",
            )
        if not standalone and _skill_router_reference(command_argv):
            return TaughtSurface(
                source,
                line_number,
                recipe,
                "yoke",
                recipe,
                "skill_router",
            )
        from yoke_cli.commands.group_help import can_route_group

        if can_route_group(command_argv):
            return TaughtSurface(
                source,
                line_number,
                recipe,
                "yoke",
                recipe,
                "navigation",
            )
        resolved = resolve_tool_shaped(command_argv)
        if resolved is None:
            if command_path_is_template(command_argv):
                return TaughtSurface(
                    source,
                    line_number,
                    recipe,
                    "yoke",
                    recipe,
                    "template",
                )
            return TaughtSurface(
                source,
                line_number,
                recipe,
                "yoke",
                recipe,
                "unresolved",
                drift_type=DRIFT_UNRESOLVED_YOKE,
            )
        adapter, remaining = resolved
        command_tokens = tuple(command_argv[: len(command_argv) - len(remaining)])
        command_form = "yoke " + " ".join(command_tokens)
        op = ops.lookup(command_form)
        return TaughtSurface(
            source,
            line_number,
            recipe,
            "yoke",
            command_form,
            "tool_shaped",
            status=op.status if op else None,
            reason=op.reason if op else None,
            drift_type=(
                None
                if adapter and op and op.status in (ops.PERMANENT, ops.TOOL_CLI)
                else DRIFT_UNRESOLVED_YOKE
            ),
        )


def _help_usage_surfaces() -> Iterable[TaughtSurface]:
    """Validate the usage lines rendered by every live CLI help page."""
    for line_number, recipe in enumerate(help_usage_recipes(), start=1):
        command_line = recipe.splitlines()[0].strip()
        if command_line.startswith("yoke "):
            yield _resolve_yoke_recipe(
                "yoke --help",
                line_number,
                command_line,
                False,
                smoke_yoke=None,
            )


def _strip_global_flags(argv: list[str]) -> tuple[list[str], bool]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--env":
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                return argv, False
            i += 2
            continue
        if token.startswith("--env="):
            if not token.split("=", 1)[1].strip():
                return argv, False
            i += 1
            continue
        out.append(token)
        i += 1
    return out, True


def _top_level_command(argv: Sequence[str]) -> bool:
    return len(argv) == 1 and argv[0] in {
        "-h",
        "--help",
        "help",
        "-V",
        "--version",
        "version",
    }


def _registered_prefix(argv: Sequence[str]) -> bool:
    head = tuple(argv)
    return bool(head) and any(
        len(head) < len(tokens) and tokens[: len(head)] == head
        for tokens in _registry_token_rows()
    )


def _skill_router_reference(argv: Sequence[str]) -> bool:
    return (
        1 <= len(argv) <= 2
        and argv[0] in _SKILL_ROUTER_ONLY
        and (len(argv) == 1 or argv[1] == "--help")
    )


def _registry_token_rows() -> tuple[tuple[str, ...], ...]:
    return (
        tuple(SUBCOMMAND_REGISTRY)
        + tuple(SUBCOMMAND_ALIAS_REGISTRY)
        + tuple(SPACE_EXPANDED_ROUTE_REGISTRY)
        + tuple(TOOL_SHAPED_SUBCOMMANDS)
    )


def _smoke_error(
    recipe: str,
    standalone: bool,
    smoke_yoke: SmokeRunner | None,
) -> str | None:
    # Fenced recipes and inline item projections carry argument contracts;
    # bare command-family references are navigation without an argument set.
    if smoke_yoke is None or (
        not standalone and not recipe.startswith("yoke items get ")
    ):
        return None
    if any(recipe.startswith(prefix) for prefix in _SMOKE_UNSAFE_PREFIXES):
        return None
    ok, _function_id, error = smoke_yoke(recipe)
    if error == "no dispatch captured":
        return None
    return None if ok else (error or "smoke failed")


__all__ = [
    "DRIFT_MISSING_REGISTERED",
    "DRIFT_MISSING_TOOL_SHAPED",
    "DRIFT_STALE_ARGUMENT_SHAPE",
    "DRIFT_UNRESOLVED_YOKE",
    "DRIFT_UNSANCTIONED_INTERNAL",
    "MissingTeaching",
    "SmokeRunner",
    "TEACHING_GLOBS",
    "TaughtSurface",
    "TeachingAudit",
    "generate_teaching_audit",
]
