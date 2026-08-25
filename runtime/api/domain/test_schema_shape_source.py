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


def test_digest_changes_when_a_schema_module_changes(tmp_path: Path) -> None:
    (tmp_path / "schema_init_columns.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "session_control_schema.py").write_text("b = 2\n", encoding="utf-8")
    before = digest_schema_shape(tmp_path)
    (tmp_path / "session_control_schema.py").write_text("b = 3\n", encoding="utf-8")
    after = digest_schema_shape(tmp_path)
    assert before != after


def test_digest_is_stable_for_the_same_bytes(tmp_path: Path) -> None:
    (tmp_path / "schema_init.py").write_text("pass\n", encoding="utf-8")
    assert digest_schema_shape(tmp_path) == digest_schema_shape(tmp_path)


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

    (domain / "schema_init.py").write_text("shape = 2\n", encoding="utf-8")
    assert digest_schema_shape(domain) != committed
    assert digest_schema_shape_commit(repo, commit_sha) == committed
