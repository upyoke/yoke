"""Recipe extraction for product-boundary teaching audits."""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import Iterable, Sequence


_FENCED_RE = re.compile(
    r"^[ \t]*```(?:bash|sh|shell)?\s*\n(.*?)^[ \t]*```",
    re.MULTILINE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_COMMAND_PREFIX_RE = re.compile(
    r"^(?:[$>]\s*)?(yoke\s+|python3?\s+-m\s+yoke_core(?:\.|\s))"
)


def extract_recipe_rows(
    root: Path,
    globs: Sequence[str],
) -> Iterable[tuple[str, int, str, bool]]:
    for path in _teaching_files(root, globs):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, recipe, standalone in _recipes_from_text(text):
            yield rel, line_number, recipe, standalone
        if path.suffix == ".py":
            # Packet recipe values may concatenate strings and carry
            # several commands. Notes and refusal text are not recipes.
            for node in ast.walk(ast.parse(text, filename=rel)):
                if not isinstance(node, ast.Dict):
                    continue
                for key, value in zip(node.keys, node.values):
                    if not isinstance(key, ast.Constant) or key.value != "recipe":
                        continue
                    if not isinstance(value, ast.Constant) or not isinstance(
                        value.value, str
                    ):
                        continue
                    for line in _packet_recipe_lines(value.value):
                        recipe = _command_from_line(line)
                        if recipe:
                            yield rel, value.lineno, recipe, False


def _packet_recipe_lines(value: str) -> Iterable[str]:
    """Split commands while keeping multiline quoted SQL/JSON together."""
    pending = ""
    for _offset, line in _join_continuations(value):
        current = pending + " " + line if pending else line
        try:
            shlex.split(current)
        except ValueError:
            pending = current
            continue
        yield current
        pending = ""
    if pending:
        yield pending


def _teaching_files(root: Path, globs: Sequence[str]) -> tuple[Path, ...]:
    found: set[Path] = set()
    for pattern in globs:
        for path in root.glob(pattern):
            if path.is_file() and not _excluded(path, root):
                found.add(path)
    return tuple(sorted(found))


def _excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return (
        len(parts) >= 2
        and parts[0] == "docs"
        and parts[1] in {"archive", "legacy-plan-artifacts"}
    )


def _recipes_from_text(text: str) -> Iterable[tuple[int, str, bool]]:
    yielded: set[tuple[int, str]] = set()
    fenced_ranges: list[tuple[int, int]] = []
    for match in _FENCED_RE.finditer(text):
        fenced_ranges.append((match.start(), match.end()))
        block_start_line = text[: match.start(1)].count("\n") + 1
        for relative_line, line in _quoted_recipe_lines(match.group(1)):
            recipe = _command_from_line(line)
            if recipe:
                key = (block_start_line + relative_line - 1, recipe)
                if key not in yielded:
                    yielded.add(key)
                    yield key[0], recipe, True
    for match in _INLINE_CODE_RE.finditer(text):
        if _inside_any(match.start(), fenced_ranges):
            continue
        recipe = _clean_recipe(match.group(1))
        if _command_like(recipe):
            key = (text[: match.start(1)].count("\n") + 1, recipe)
            if key not in yielded:
                yielded.add(key)
                yield key[0], recipe, False


def _join_continuations(block: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    raw_lines = block.split("\n")
    i = 0
    while i < len(raw_lines):
        line_no_offset = i + 1
        current = raw_lines[i]
        while current.rstrip().endswith("\\") and (i + 1) < len(raw_lines):
            current = current.rstrip()[:-1].rstrip() + " " + raw_lines[i + 1]
            i += 1
        out.append((line_no_offset, current))
        i += 1
    return out


def _quoted_recipe_lines(block: str) -> Iterable[tuple[int, str]]:
    """Keep literal multiline JSON arguments intact with their source line."""
    pending = ""
    start = 0
    for line_number, line in _join_continuations(block):
        if not pending:
            if _command_from_line(line) is None:
                yield line_number, line
                continue
            start = line_number
            line = line.split(" #", 1)[0]
        current = pending + " " + line if pending else line
        try:
            shlex.split(current)
        except ValueError:
            pending = current
            continue
        yield start, current
        pending = ""
    if pending:
        yield start, pending


def _command_from_line(line: str) -> str | None:
    stripped = line.strip()
    while stripped.startswith(("-", "*")):
        stripped = stripped[1:].strip()
    return _clean_recipe(stripped) if _command_like(stripped) else None


def _command_like(recipe: str) -> bool:
    return bool(_COMMAND_PREFIX_RE.match(recipe)) and not _generic_recipe(recipe)


def _inside_any(offset: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _clean_recipe(recipe: str) -> str:
    recipe = recipe.strip().strip("`")
    recipe = (
        recipe[1:-1]
        if len(recipe) > 1 and recipe[0] == recipe[-1] and recipe[0] in "'\""
        else recipe
    )
    return recipe.split(" #", 1)[0].strip().rstrip(",:")


def _generic_recipe(recipe: str) -> bool:
    return "..." in recipe or "<subcommand>" in recipe or recipe == "yoke <subcommand>"


__all__ = ["extract_recipe_rows"]
