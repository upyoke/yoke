"""Tests for codex_entry.py — Codex harness entry launcher.

Covers: manifest reading, identity resolution, env rendering, command routing,
and help output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain.harness_capability_registry import (
    shared_downstream_paths,
    shared_entrypoints,
)
from runtime.harness.codex.codex_entry import (
    CodexIdentity,
    manifest_read,
    route_advance,
    route_polish,
    route_usher,
    show_env,
    show_help,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def codex_root(tmp_path, monkeypatch):
    """Create a minimal Codex harness file tree."""
    manifest = {
        "identity": {"executor": "codex"},
        "supports": {"command_source": "shared_yoke_registry"},
    }
    harness = tmp_path / "runtime" / "harness" / "codex"
    harness.mkdir(parents=True)
    manifest_path = harness / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    spec = tmp_path / "runtime" / "harness" / "bootstrap-spec.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(json.dumps({"required_files": [], "recommended_files": []}))

    # Clear env so identity resolution is deterministic
    monkeypatch.delenv("YOKE_EXECUTOR", raising=False)
    monkeypatch.delenv("YOKE_PROVIDER", raising=False)
    monkeypatch.delenv("YOKE_MODEL", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(tmp_path))

    return tmp_path, manifest_path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestManifestRead:
    def test_reads_nested_path(self, codex_root):
        _, manifest_path = codex_root
        assert manifest_read(manifest_path, "identity.executor") == "codex"

    def test_returns_empty_for_missing_key(self, codex_root):
        _, manifest_path = codex_root
        assert manifest_read(manifest_path, "identity.nonexistent") == ""

    def test_returns_empty_for_missing_file(self, tmp_path):
        assert manifest_read(tmp_path / "nope.json", "foo") == ""

    def test_list_values_joined(self, codex_root):
        _, manifest_path = codex_root
        result = manifest_read(manifest_path, "supports.command_source")
        assert result == "shared_yoke_registry"

    def test_repo_manifest_uses_shared_command_source(self):
        manifest_path = Path(__file__).with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        supports = manifest["supports"]
        assert supports["command_source"] == "shared_yoke_registry"
        assert "entrypoints" not in supports
        assert "downstream_paths" not in supports
        assert "/yoke usher" in shared_entrypoints()
        assert "usher" in shared_downstream_paths()


class TestCodexIdentity:
    def test_defaults(self, codex_root, monkeypatch):
        root, _ = codex_root
        # Patch resolve_runtime_model to avoid real Codex lookups
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        # AC-11 exception: this fixture deliberately exercises the
        # coarse `codex` family-fallback path (no surface env vars set) so
        # CodexIdentity must emit the coarse value, not a `codex-*` variant.
        assert identity.executor == "codex"
        assert identity.provider == "openai"
        assert identity.display_model() == "(unresolved)"

    def test_env_overrides(self, codex_root, monkeypatch):
        root, _ = codex_root
        monkeypatch.setenv("YOKE_EXECUTOR", "test-exec")
        monkeypatch.setenv("YOKE_PROVIDER", "test-prov")
        monkeypatch.setenv("YOKE_MODEL", "test-model")
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        assert identity.executor == "test-exec"
        assert identity.provider == "test-prov"
        assert identity.display_model() == "test-model"

    def test_entrypoints(self, codex_root, monkeypatch):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        ep = identity.entrypoints()
        assert "/yoke idea" in ep

    def test_downstream_paths(self, codex_root, monkeypatch):
        root, manifest_path = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        assert identity.downstream_paths() == "shepherd, refine, advance, polish, usher"


class TestShowEnv:
    def test_prints_exports(self, codex_root, monkeypatch, capsys):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        show_env(identity)
        out = capsys.readouterr().out
        assert "export YOKE_EXECUTOR=" in out
        assert "export YOKE_PROVIDER=" in out


class TestShowHelp:
    def test_prints_commands(self, codex_root, monkeypatch, capsys):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)
        show_help(identity)
        out = capsys.readouterr().out
        assert "bootstrap" in out
        assert "env" in out
        assert "idea" in out
        assert "advance" in out
        assert "usher" in out
        assert "Downstream paths:" in out


class TestRouteAdvance:
    def test_prints_guidance_only_advance_handoff(self, codex_root, monkeypatch, capsys):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)

        route_advance(identity, ["YOK-9999", "implementation"])

        out = capsys.readouterr().out
        assert "This wrapper displays guidance only" in out
        assert "does not claim the item" in out
        assert "create a worktree" in out
        assert "/yoke advance YOK-9999 implementation" in out
        assert "implementation worktree" in out


class TestRoutePolish:
    def test_prints_guidance_only_polish_handoff(self, codex_root, monkeypatch, capsys):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)

        route_polish(identity, ["YOK-9999"])

        out = capsys.readouterr().out
        assert "This wrapper displays guidance only" in out
        assert "does not claim the item" in out
        assert "update status" in out
        assert "/yoke polish YOK-9999" in out
        assert "recorded worktree" in out


class TestRouteUsher:
    def test_prints_guidance_only_usher_handoff(self, codex_root, monkeypatch, capsys):
        root, _ = codex_root
        monkeypatch.setattr(
            "runtime.harness.codex.codex_entry.resolve_runtime_model",
            lambda r: "",
        )
        identity = CodexIdentity(root)

        route_usher(identity, ["YOK-9999", "--dry-run"])

        out = capsys.readouterr().out
        assert "This wrapper displays guidance only" in out
        assert "does not claim the item" in out
        assert "merge branches" in out
        assert "/yoke usher YOK-9999 --dry-run" in out
        assert "run it with --dry-run" in out
