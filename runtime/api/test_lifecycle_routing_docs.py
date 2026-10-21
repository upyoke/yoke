"""Bootstrap and shared-registry guards for workflow lifecycle routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.harness_capability_registry import (
    shared_downstream_paths,
    shared_entrypoints,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TestBootstrapSpec — canonical lifecycle guide is loaded at bootstrap
# ---------------------------------------------------------------------------


class TestBootstrapSpec:
    """Bootstrap must load yoke/.yoke/docs/workflows/lifecycle.md."""

    @pytest.fixture
    def spec(self) -> dict:
        path = REPO / "runtime" / "harness" / "bootstrap-spec.json"
        return json.loads(_read(path))

    def test_required_files_includes_lifecycle(self, spec):
        required = spec.get("required_files", [])
        assert ".yoke/docs/workflows/lifecycle.md" in required, (
            "bootstrap-spec.json must include yoke/.yoke/docs/workflows/lifecycle.md in required_files"
        )

    def test_lifecycle_loaded_after_commands(self, spec):
        """lifecycle.md should follow commands.md so readers get command
        vocabulary before the lifecycle tables that use it."""
        required = spec.get("required_files", [])
        assert ".yoke/docs/agents/commands.md" in required
        assert required.index(".yoke/docs/workflows/lifecycle.md") > required.index(
            ".yoke/docs/agents/commands.md"
        )


# ---------------------------------------------------------------------------
# TestCodexCapabilityDocs — the shared registry advertises canonical paths
# ---------------------------------------------------------------------------


class TestCodexCapabilityDocs:
    """The Codex manifest defers entrypoints to the shared registry."""

    @pytest.fixture
    def manifest(self) -> dict:
        path = REPO / "runtime" / "harness" / "codex" / "manifest.json"
        return json.loads(_read(path))

    def test_shared_registry_declares_canonical_entrypoints(self, manifest):
        supports = manifest.get("supports", {})
        assert supports.get("command_source") == "shared_yoke_registry"
        assert "entrypoints" not in supports
        entrypoints = shared_entrypoints()
        expected = {
            "/yoke idea",
            "/yoke refine",
            "/yoke implement",
            "/yoke polish",
            "/yoke usher",
        }
        assert expected.issubset(set(entrypoints)), (
            f"shared registry must advertise {expected}, got {entrypoints}"
        )

    def test_shared_registry_declares_canonical_downstream_paths(self, manifest):
        supports = manifest.get("supports", {})
        assert "downstream_paths" not in supports
        paths = shared_downstream_paths()
        expected = {"shepherd", "refine", "implement", "polish", "usher"}
        assert expected.issubset(set(paths)), (
            f"shared registry must advertise {expected} downstream paths, got {paths}"
        )
