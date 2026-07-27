"""Source-packaging contract for every declared governed migration."""

from __future__ import annotations

import ast
import importlib.util
import json
import shlex
from pathlib import Path

import pytest

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest

_ROOT = Path(__file__).resolve().parents[4]
_MANIFESTS = tuple(sorted(Path(__file__).parent.glob("*.migration.json")))


@pytest.mark.parametrize("manifest_path", _MANIFESTS, ids=lambda path: path.stem)
def test_manifest_binds_runnable_tracked_sources(manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _, profile, attestation = validate_manifest_payload(payload)

    assert profile["mutation_intent"] == "apply"
    for identifier in profile["migration_modules"]:
        runner = manifest_path.with_name(f"{identifier}.py")
        assert runner.is_file(), f"missing governed runner: {runner.relative_to(_ROOT)}"
        spec = importlib.util.spec_from_file_location(
            f"_migration_packaging_{identifier}",
            runner,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "MIGRATION_NAME"):
            assert module.MIGRATION_NAME == identifier
        assert callable(module.apply)

        source = payload["module_sources"][identifier]
        source_path = _ROOT / source["path"]
        assert source_path.is_file(), f"missing packaged source: {source['path']}"
        assert migration_source_digest(source_path) == source["sha256"]

    for command in attestation["rehearsal_commands"]:
        for token in shlex.split(command):
            if token.endswith(".py"):
                assert (_ROOT / token).is_file(), (
                    f"rehearsal command names missing test: {token}"
                )


@pytest.mark.parametrize("manifest_path", _MANIFESTS, ids=lambda path: path.stem)
def test_manifest_attestations_name_live_symbols(manifest_path: Path) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    _, _, attestation = validate_manifest_payload(payload)

    for entry in attestation["pre_merge_readers_writers"]:
        source_path = _ROOT / entry["path"]
        assert source_path.is_file(), f"attestation path is missing: {entry['path']}"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        definitions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
        }
        assert entry["symbol"] in definitions, (
            f"attestation symbol is missing: {entry['path']}::{entry['symbol']}"
        )
