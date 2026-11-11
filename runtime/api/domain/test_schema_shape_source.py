"""The schema-shape digest the release gate records and reads."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.schema_shape_source import (
    SchemaShapeSourceError,
    digest_schema_shape,
    digest_schema_shape_commit,
    schema_shape_files,
)


def test_boot_converge_schema_modules_are_in_the_digest_set() -> None:
    names = {path.name for path in schema_shape_files()}
    assert "schema_init_columns.py" in names
    assert "session_control_schema.py" in names
    assert "schema_init.py" in names


def test_packet_modules_are_not_in_the_digest_set() -> None:
    names = {path.name for path in schema_shape_files()}
    assert "schema_api_context.py" not in names
    assert not any(name.startswith("schema_api_context_") for name in names)


def test_digest_changes_when_a_schema_declaration_changes(tmp_path: Path) -> None:
    (tmp_path / "schema_init_columns.py").write_text(
        'DDL = "CREATE TABLE widget (id INTEGER)"\n', encoding="utf-8"
    )
    before = digest_schema_shape(tmp_path)
    (tmp_path / "schema_init_columns.py").write_text(
        'DDL = "CREATE TABLE widget (id INTEGER, name TEXT)"\n', encoding="utf-8"
    )
    after = digest_schema_shape(tmp_path)
    assert before != after


def test_digest_ignores_comments_docstrings_and_formatting(tmp_path: Path) -> None:
    source = tmp_path / "schema_init.py"
    source.write_text(
        '''"""Original module description."""

# Original comment.
def apply(conn):
    """Original function description."""
    conn.execute("CREATE TABLE widget (id INTEGER)")
''',
        encoding="utf-8",
    )
    before = digest_schema_shape(tmp_path)

    source.write_text(
        '''"""A rewritten module description."""

def apply( conn ):
    """A rewritten function description."""
    # A newly worded comment.
    conn.execute(
        'CREATE TABLE widget (id INTEGER)'
    )
''',
        encoding="utf-8",
    )

    assert digest_schema_shape(tmp_path) == before


def test_an_empty_source_set_refuses_rather_than_inventing_a_digest(
    tmp_path: Path,
) -> None:
    (tmp_path / "schema_api_context.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("pass\n", encoding="utf-8")
    with pytest.raises(SchemaShapeSourceError):
        digest_schema_shape(tmp_path)


def test_commit_digest_reads_the_release_tree_not_dirty_checkout(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    domain = repo / "packages" / "yoke-core" / "src" / "yoke_core" / "domain"
    domain.mkdir(parents=True)
    (domain / "schema_init.py").write_text("shape = 1\n", encoding="utf-8")
    (domain / "session_control_schema.py").write_text(
        "session_shape = 1\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "base",
        ],
        cwd=repo,
        check=True,
    )
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    committed = digest_schema_shape_commit(repo, commit_sha)
    assert committed == digest_schema_shape(domain)

    (domain / "schema_init.py").write_text(
        "# Descriptive edit only.\nshape = 1\n", encoding="utf-8"
    )
    assert digest_schema_shape(domain) == committed

    (domain / "schema_init.py").write_text("shape = 2\n", encoding="utf-8")
    assert digest_schema_shape(domain) != committed
    assert digest_schema_shape_commit(repo, commit_sha) == committed


# Golden digests. A change here orphans every fleet-rehearsal receipt already
# recorded, and a mismatch on only one CI interpreter means the digest has
# become Python-version dependent again: the release driver and the on-box
# preflight executor run different interpreters and must agree.
_GOLDEN_FIXTURE = '''"""Fixture module."""
from typing import Optional
TABLE = "widget"
WIDTH: int = 12
COLUMNS = [("id", "INTEGER"), ("name", "TEXT")]


def ddl(table: str = TABLE, *cols, check: Optional[str] = None, **opts) -> str:
    """Build DDL."""
    body = ", ".join(f"{name} {kind}" for name, kind in COLUMNS)
    tail = f" CHECK ({check!r:>{WIDTH}})" if check is not None else ""
    return f"CREATE TABLE {table} ({body}){tail} -- {len(cols):03d} {opts}"


class Widget:
    """A row."""
    flags = {"a": None, "b": True, "c": ...}

    async def load(self, conn, /, limit=None):
        match limit:
            case None:
                return [row async for row in conn]
            case int(n) if n > 0:
                return await conn.fetch(f"SELECT * FROM {TABLE} LIMIT {n}")
            case [first, *rest]:
                return {first: rest}
            case _:
                raise ValueError(f"bad limit {limit=}")
'''
_GOLDEN_FIXTURE_DIGEST = (
    "f532e45f92fd3bc76b16b41d67f94228d37317aa9317796288c04e16fdfd8736"
)
_GOLDEN_COMMIT = "f9f8d0924c77ca0133c00836da1a227952623cd4"
_GOLDEN_COMMIT_DIGEST = (
    "87c23c029594de90e4f10bbfdaea7a50aaf0d1466bf1de8eb5c8239d3387f45e"
)


def test_fixture_digest_is_the_same_on_every_python(tmp_path: Path) -> None:
    (tmp_path / "schema_init.py").write_text(_GOLDEN_FIXTURE, encoding="utf-8")
    assert digest_schema_shape(tmp_path) == _GOLDEN_FIXTURE_DIGEST


def test_real_tree_digest_is_the_same_on_every_python() -> None:
    repository = Path(__file__).resolve().parents[3]
    assert digest_schema_shape_commit(repository, _GOLDEN_COMMIT) == (
        _GOLDEN_COMMIT_DIGEST
    )
