"""Portable governed-migration contract for hosted engine databases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.portable_migration import (
    PortableManifest,
    PortableMigrationError,
    apply_manifest,
    load_packaged_modules,
    parse_manifest_text,
    row_counts,
)
from yoke_core.domain.migration_source_digest import migration_source_digest


MODULE = "sample_portable_migration"


def _manifest(tmp_path: Path) -> tuple[str, PortableManifest, Path]:
    source = tmp_path / f"{MODULE}.py"
    source.write_text("def apply(conn):\n    return None\n", encoding="utf-8")
    payload = {
        "version": 1,
        "project": "external-project",
        "profile": {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [MODULE],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [{"table": "items", "columns": ["id"]}],
            "count_preserving": True,
        },
        "module_sources": {
            MODULE: {
                "path": source.name,
                "sha256": migration_source_digest(source),
            }
        },
        "attestation": {
            "pre_merge_readers_writers": [
                {"path": source.name, "symbol": "apply", "role": "writer"}
            ],
            "invariants": ["The synthetic apply preserves item rows."],
            "rehearsal_commands": ["python3 -c 'print(\"rehearsal\")'"],
            "residual_risk_notes": "Synthetic portable migration fixture.",
        },
    }
    raw = json.dumps(payload, sort_keys=True)
    return raw, parse_manifest_text(raw), source


def _module(source: Path) -> SimpleNamespace:
    return SimpleNamespace(
        __name__=f"yoke_core.domain.migrations.{MODULE}",
        __file__=str(source),
        apply=lambda _conn: None,
    )


def test_manifest_text_keeps_exact_digest_and_loads_packaged_module(
    tmp_path,
    monkeypatch,
) -> None:
    raw, manifest, source = _manifest(tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.portable_migration.importlib.import_module",
        lambda _name: _module(source),
    )

    assert manifest.project == "external-project"
    assert manifest.module_identifiers == (MODULE,)
    assert manifest.affected_tables == ("items",)
    assert manifest.module_sources[MODULE]["sha256"] == migration_source_digest(source)
    assert manifest.sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    modules = load_packaged_modules(manifest)
    assert modules[0].__name__ == f"yoke_core.domain.migrations.{MODULE}"


def test_portable_apply_uses_packaged_module_and_returns_secret_free_counts(
    tmp_path,
    monkeypatch,
) -> None:
    _, manifest, source = _manifest(tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.portable_migration.load_packaged_modules",
        lambda _manifest: (_module(source),),
    )
    with pg_testdb.test_database() as conn:
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


def test_portable_apply_rolls_back_when_module_refuses(
    monkeypatch,
    tmp_path,
) -> None:
    _, manifest, _ = _manifest(tmp_path)
    with pg_testdb.test_database() as conn:
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
    _, manifest, _ = _manifest(tmp_path)
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
    _, manifest, _ = _manifest(tmp_path)
    source = tmp_path / f"{MODULE}.py"
    source.write_text("def apply(conn):\n    return conn\n", encoding="utf-8")
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
    _, manifest, _ = _manifest(tmp_path)
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
    tmp_path,
) -> None:
    _, manifest, _ = _manifest(tmp_path)
    with pg_testdb.test_database() as conn:
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
