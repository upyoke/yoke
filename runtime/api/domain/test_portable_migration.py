"""Portable governed-migration contract for hosted engine databases."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.portable_migration import (
    PortableMigrationError,
    apply_manifest,
    load_packaged_modules,
    parse_manifest_text,
    row_counts,
)
from yoke_core.domain.migration_source_digest import migration_source_digest


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = (
    ROOT
    / "runtime/api/domain/migrations/item_dependency_public_ref_repair.migration.json"
)
PROJECT_IDENTITY_POLICY_MANIFEST = (
    ROOT
    / "runtime/api/domain/migrations/project_identity_policy_backfill.migration.json"
)
MODULE = "item_dependency_public_ref_repair"


def test_manifest_text_keeps_exact_digest_and_loads_packaged_module() -> None:
    raw = MANIFEST.read_text(encoding="utf-8")
    manifest = parse_manifest_text(raw)

    assert manifest.project == "yoke"
    assert manifest.module_identifiers == (MODULE,)
    assert manifest.affected_tables == ("item_dependencies",)
    source = ROOT / manifest.module_sources[MODULE]["path"]
    assert manifest.module_sources[MODULE]["sha256"] == migration_source_digest(source)
    assert manifest.sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    modules = load_packaged_modules(manifest)
    assert modules[0].__name__ == f"yoke_core.domain.migrations.{MODULE}"


def test_portable_apply_uses_packaged_module_and_returns_secret_free_counts() -> None:
    with pg_testdb.test_database() as conn:
        manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
        before = row_counts(conn, manifest.affected_tables)

        result = apply_manifest(conn, manifest)

        assert result.modules == (MODULE,)
        assert result.pre_row_counts == before
        assert result.post_row_counts == before
        assert result.baseline_verification == {
            "integrity_check": "ok",
            "fk_violations": 0,
            "post_row_counts": before,
            "pre_row_counts": before,
            "count_preserving": True,
            "failures": [],
        }
        assert row_counts(conn, manifest.affected_tables) == before


def test_project_identity_policy_backfill_is_portable_and_idempotent() -> None:
    with pg_testdb.test_database() as conn:
        manifest = parse_manifest_text(
            PROJECT_IDENTITY_POLICY_MANIFEST.read_text(encoding="utf-8")
        )

        first = apply_manifest(conn, manifest)
        second = apply_manifest(conn, manifest)

        assert first.modules == (
            "harness_session_project_identity",
            "project_policy_capabilities",
        )
        assert second.modules == first.modules
        assert first.baseline_verification["failures"] == []
        assert second.baseline_verification["failures"] == []


def test_portable_apply_rolls_back_when_module_refuses(monkeypatch) -> None:
    with pg_testdb.test_database() as conn:
        manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
        before = row_counts(conn, manifest.affected_tables)
        module = SimpleNamespace(
            __name__="package.refusing_apply",
            apply=lambda _conn: (_ for _ in ()).throw(
                RuntimeError("synthetic refusal")
            ),
        )
        monkeypatch.setattr(
            "yoke_core.domain.portable_migration.load_packaged_modules",
            lambda _manifest: (module,),
        )

        with pytest.raises(RuntimeError, match="synthetic refusal"):
            apply_manifest(conn, manifest)

        assert row_counts(conn, manifest.affected_tables) == before


def test_portable_manifest_refuses_untracked_theorem_shape() -> None:
    with pytest.raises(PortableMigrationError, match="keys invalid"):
        parse_manifest_text('{"version":1,"project":"yoke","extra":true}')


def test_row_counts_refuses_non_identifier_table() -> None:
    class NeverExecutes:
        def execute(self, _query):
            raise AssertionError("unsafe table reached SQL execution")

    with pytest.raises(PortableMigrationError, match="bare SQL identifier"):
        row_counts(NeverExecutes(), ("events; DROP TABLE events",))


def test_packaged_module_invariants_hook_is_optional(monkeypatch, tmp_path) -> None:
    manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
    source = tmp_path / f"{MODULE}.py"
    source.write_text("def apply(conn):\n    return None\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = replace(
        manifest,
        module_sources={
            MODULE: {
                "path": f"{MODULE}.py",
                "sha256": digest,
            }
        },
    )
    module = SimpleNamespace(
        __name__="package.optional",
        __file__=str(source),
        apply=lambda _conn: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.portable_migration.importlib.import_module",
        lambda _name: module,
    )

    assert load_packaged_modules(manifest) == (module,)


def test_packaged_module_digest_must_match_manifest(monkeypatch, tmp_path) -> None:
    manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
    source = tmp_path / f"{MODULE}.py"
    source.write_text("def apply(conn):\n    return None\n", encoding="utf-8")
    module = SimpleNamespace(
        __name__="package.changed",
        __file__=str(source),
        apply=lambda _conn: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.portable_migration.importlib.import_module",
        lambda _name: module,
    )

    with pytest.raises(PortableMigrationError, match="digest differs"):
        load_packaged_modules(manifest)


def test_packaged_module_dependency_drift_must_match_manifest(
    monkeypatch,
    tmp_path,
) -> None:
    manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
    source = tmp_path / "root.py"
    dependency = tmp_path / "helper.py"
    source.write_text(
        "from yoke_core.domain.migrations.helper import run\n"
        "def apply(conn):\n"
        "    return run(conn)\n",
        encoding="utf-8",
    )
    dependency.write_text("def run(conn):\n    return conn\n", encoding="utf-8")
    manifest = replace(
        manifest,
        module_sources={
            MODULE: {
                "path": "root.py",
                "sha256": migration_source_digest(source),
            }
        },
    )
    module = SimpleNamespace(
        __name__="package.changed_dependency",
        __file__=str(source),
        apply=lambda _conn: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.portable_migration.importlib.import_module",
        lambda _name: module,
    )
    dependency.write_text(
        "def run(conn):\n    return (conn, 'changed')\n",
        encoding="utf-8",
    )

    with pytest.raises(PortableMigrationError, match="digest differs"):
        load_packaged_modules(manifest)


def test_verification_failure_carries_secret_free_baseline_evidence(
    monkeypatch,
) -> None:
    with pg_testdb.test_database() as conn:
        manifest = parse_manifest_text(MANIFEST.read_text(encoding="utf-8"))
        before = row_counts(conn, manifest.affected_tables)

        def invariant(_conn):
            raise AssertionError("synthetic invariant refusal")

        module = SimpleNamespace(
            __name__="package.refusing",
            apply=lambda _conn: None,
            invariants=invariant,
        )
        monkeypatch.setattr(
            "yoke_core.domain.portable_migration.load_packaged_modules",
            lambda _manifest: (module,),
        )

        with pytest.raises(
            PortableMigrationError, match="synthetic invariant refusal"
        ) as excinfo:
            apply_manifest(conn, manifest)

        assert excinfo.value.baseline_verification == {
            "integrity_check": "ok",
            "fk_violations": 0,
            "post_row_counts": before,
            "pre_row_counts": before,
            "count_preserving": True,
            "failures": [],
        }
