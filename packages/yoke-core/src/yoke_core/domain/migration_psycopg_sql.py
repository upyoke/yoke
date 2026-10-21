"""Reject bare percent tokens in parameterized migration SQL before psycopg.

psycopg reads ``%`` in a parameterized statement as a placeholder, so a
literal ``'%x%'`` beside a params argument fails only when the migration
runs. The check reads every non-test module in a history directory, because
entries import sibling helpers. Each source is parsed once per process for
its path and content digest; an edited file is checked again.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from yoke_core.domain.migration_apply_contract import ModuleContractError
from yoke_core.domain.migration_content_identity import raw_content_sha256

_PSYCOPG_PERCENT_TOKEN = re.compile(r"%(?:%|[sbt]|\([^)]+\)[sbt])")


def _contains_bare_percent(sql: str) -> bool:
    position = 0
    while True:
        position = sql.find("%", position)
        if position < 0:
            return False
        token = _PSYCOPG_PERCENT_TOKEN.match(sql, position)
        if token is None:
            return True
        position = token.end()


def _literal_sql_fragments(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.JoinedStr):
        return tuple(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ()


#: Sources already proven free of bare percent tokens, by path and content
#: digest. Boot loads every entry and each load checks the whole directory,
#: so without this a birth parsed the directory once per entry.
_PSYCOPG_CLEAN_SOURCES: set[tuple[str, str]] = set()


def _check_psycopg_source(source_path: Path, raw: bytes) -> None:
    key = (str(source_path), raw_content_sha256(raw))
    if key in _PSYCOPG_CLEAN_SOURCES:
        return
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(source_path))
    except (SyntaxError, UnicodeDecodeError):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {
            "execute",
            "executemany",
        }:
            continue
        has_params = len(node.args) > 1 or any(
            keyword.arg in {"params", "parameters"} for keyword in node.keywords
        )
        statement = node.args[0]
        has_bare_percent = any(
            _contains_bare_percent(fragment)
            for fragment in _literal_sql_fragments(statement)
        )
        if has_params and has_bare_percent:
            raise ModuleContractError(
                f"migration authoring check failed at "
                f"{source_path.name}:{statement.lineno}: parameterized "
                "execute() SQL contains a bare '%'; use '%%' for a literal "
                "percent, or omit the params argument for parameter-free SQL"
            )
    _PSYCOPG_CLEAN_SOURCES.add(key)


def validate_psycopg_migration_sql(
    directory: Path,
    *,
    override_path: Path | None = None,
    override_source: bytes | None = None,
) -> None:
    """Reject bare percent tokens in parameterized SQL before psycopg runs it."""
    for source_path in sorted(directory.glob("*.py")):
        if source_path.name.startswith("test_"):
            continue
        raw = (
            override_source
            if source_path == override_path and override_source is not None
            else source_path.read_bytes()
        )
        _check_psycopg_source(source_path, raw)


__all__ = ["validate_psycopg_migration_sql"]
