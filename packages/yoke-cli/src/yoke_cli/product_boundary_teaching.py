"""Taught recipe surface audit for the installable ``yoke`` CLI."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple

from yoke_cli import operation_inventory as ops
from yoke_cli.commands.registry import (
    SUBCOMMAND_ALIAS_REGISTRY,
    SUBCOMMAND_REGISTRY,
    resolve,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS, resolve_tool_shaped
from yoke_cli.product_boundary_teaching_extract import extract_recipe_rows


SmokeRunner = Callable[[str], Tuple[bool, Optional[str], Optional[str]]]

TEACHING_GLOBS: Tuple[str, ...] = (
    ".agents/skills/yoke/**/*.md",
    "runtime/agents/*.md",
    "runtime/harness/claude/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
    "packages/yoke-core/src/yoke_core/domain/schema_api_context*.py",
    "AGENTS.md",
    "CODEX.md",
    "docs/**/*.md",
)

DRIFT_UNRESOLVED_YOKE = "taught_yoke_command_unresolved"
DRIFT_UNSANCTIONED_INTERNAL = "taught_internal_module_unsanctioned"
DRIFT_MISSING_REGISTERED = "registered_command_missing_from_teaching"
DRIFT_MISSING_TOOL_SHAPED = "tool_shaped_command_missing_from_teaching"
DRIFT_STALE_ARGUMENT_SHAPE = "stale_argument_shape"
_SKILL_ROUTER_ONLY = frozenset({"idea"})
_SMOKE_UNSAFE_PREFIXES = ("yoke board rebuild", "yoke strategy render", "yoke strategy ingest")

_PY_MODULE_RE = re.compile(r"^python3?\s+-m\s+yoke_core(?:\.[A-Za-z_]\w*)+")
_TEMPLATE_RE = re.compile(
    r"\{[^}]+\}"
    r"|\$[A-Za-z_][\w]*"
    r"|\$\{[^}]+\}"
    r"|\$\("
    r"|\bYOK-N\b"
    r"|\b[A-Z_]*PATH\b"
    r"|<[^>]+>"
    r"|\\$"
    r"|2>&1"
    r"|[<>]/?\S*"
    r"|\|\|"
    r"|&&"
)


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


def generate_teaching_audit(
    *,
    repo_root: Path | str,
    smoke_yoke: SmokeRunner | None = None,
) -> TeachingAudit:
    root = Path(repo_root).resolve()
    surfaces = tuple(_extract_surfaces(root, smoke_yoke=smoke_yoke))
    taught_forms = {
        row.command_form
        for row in surfaces
        if row.kind == "yoke" and row.resolution in {"registered", "alias", "tool_shaped"}
    }
    missing = tuple(
        sorted(
            _missing_teaching_rows(taught_forms),
            key=lambda r: (r.drift_type, r.command_form),
        )
    )
    return TeachingAudit(
        surfaces=tuple(sorted(surfaces, key=lambda r: (r.source, r.line_number, r.recipe))),
        missing=missing,
    )


def _extract_surfaces(
    root: Path,
    *,
    smoke_yoke: SmokeRunner | None,
) -> Iterable[TaughtSurface]:
    for rel, line_number, recipe, standalone in extract_recipe_rows(root, TEACHING_GLOBS):
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
            source, line_number, recipe, "yoke", recipe, "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE, smoke_error=str(exc),
        )
    if not argv or argv[0] != "yoke":
        return TaughtSurface(
            source, line_number, recipe, "yoke", recipe, "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE,
        )
    command_argv, globals_ok = _strip_global_flags(argv[1:])
    if not globals_ok:
        return TaughtSurface(
            source, line_number, recipe, "yoke", recipe, "parse_error",
            drift_type=DRIFT_UNRESOLVED_YOKE,
        )
    if _top_level_command(command_argv):
        return TaughtSurface(
            source, line_number, recipe, "yoke", recipe, "top_level",
        )
    try:
        tokens, function_id, _adapter, _remaining = resolve(command_argv)
        command_form = "yoke " + " ".join(tokens)
        resolution = "alias" if tokens in SUBCOMMAND_ALIAS_REGISTRY else "registered"
        smoke_error = _smoke_error(recipe, standalone, smoke_yoke)
        return TaughtSurface(
            source, line_number, recipe, "yoke", command_form, resolution,
            function_id=function_id,
            drift_type=DRIFT_STALE_ARGUMENT_SHAPE if smoke_error else None,
            smoke_error=smoke_error,
        )
    except KeyError:
        if not standalone and _registered_prefix(command_argv):
            return TaughtSurface(
                source, line_number, recipe, "yoke", recipe, "namespace_prefix",
            )
        if not standalone and _skill_router_reference(command_argv):
            return TaughtSurface(
                source, line_number, recipe, "yoke", recipe, "skill_router",
            )
        resolved = resolve_tool_shaped(command_argv)
        if resolved is None:
            return TaughtSurface(
                source, line_number, recipe, "yoke", recipe, "unresolved",
                drift_type=DRIFT_UNRESOLVED_YOKE,
            )
        adapter, remaining = resolved
        command_tokens = tuple(command_argv[:len(command_argv) - len(remaining)])
        command_form = "yoke " + " ".join(command_tokens)
        op = ops.lookup(command_form)
        return TaughtSurface(
            source, line_number, recipe, "yoke", command_form, "tool_shaped",
            status=op.status if op else None,
            reason=op.reason if op else None,
            drift_type=None if adapter and op and op.status == ops.PERMANENT else DRIFT_UNRESOLVED_YOKE,
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
    return len(argv) == 1 and argv[0] in {"-h", "--help", "help", "-V", "--version", "version"}


def _registered_prefix(argv: Sequence[str]) -> bool:
    head = tuple(argv)
    return bool(head) and any(
        len(head) < len(tokens) and tokens[:len(head)] == head
        for tokens in _registry_token_rows()
    )


def _skill_router_reference(argv: Sequence[str]) -> bool:
    return 1 <= len(argv) <= 2 and argv[0] in _SKILL_ROUTER_ONLY and (len(argv) == 1 or argv[1] == "--help")


def _registry_token_rows() -> tuple[tuple[str, ...], ...]:
    return tuple(SUBCOMMAND_REGISTRY) + tuple(SUBCOMMAND_ALIAS_REGISTRY) + tuple(TOOL_SHAPED_SUBCOMMANDS)


def _smoke_error(
    recipe: str,
    standalone: bool,
    smoke_yoke: SmokeRunner | None,
) -> str | None:
    if smoke_yoke is None or _TEMPLATE_RE.search(recipe) or not standalone:
        return None
    if any(recipe.startswith(prefix) for prefix in _SMOKE_UNSAFE_PREFIXES):
        return None
    ok, _function_id, error = smoke_yoke(recipe)
    if error == "no dispatch captured":
        return None
    return None if ok else (error or "smoke failed")


def _resolve_python_recipe(source: str, line_number: int, recipe: str) -> TaughtSurface:
    recipe_tokens = _split_or_empty(recipe)
    best: ops.OperationEntry | None = None
    for entry in ops.all_entries():
        if not entry.shell_form.startswith("python"):
            continue
        entry_tokens = _split_or_empty(entry.shell_form)
        if recipe_tokens[:len(entry_tokens)] == entry_tokens:
            if best is None or len(entry_tokens) > len(_split_or_empty(best.shell_form)):
                best = entry
    if best and best.status == ops.PERMANENT:
        return TaughtSurface(
            source, line_number, recipe, "python_module", best.shell_form,
            "permanent", status=best.status, reason=best.reason,
        )
    return TaughtSurface(
        source, line_number, recipe, "python_module",
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
    registry_forms.update({
        "yoke " + " ".join(tokens): (function_id, True)
        for tokens, (function_id, _adapter) in SUBCOMMAND_ALIAS_REGISTRY.items()
    })
    for command_form, (function_id, is_alias) in registry_forms.items():
        if command_form not in taught_forms:
            yield MissingTeaching(
                command_form, "alias" if is_alias else "registered",
                function_id, DRIFT_MISSING_REGISTERED,
            )
    for tokens in TOOL_SHAPED_SUBCOMMANDS:
        command_form = "yoke " + " ".join(tokens)
        if command_form not in taught_forms:
            yield MissingTeaching(command_form, "tool_shaped", None, DRIFT_MISSING_TOOL_SHAPED)


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
