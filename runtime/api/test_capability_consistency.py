"""Regression: the shared registry and harness manifest agree on capabilities.

Command/path truth flows from the shared Yoke registry; each harness manifest
only declares identity and explicit substrate limitations. Every registered
operator command resolves to an existing skill.
"""

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
HARNESS = REPO / "runtime" / "harness"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


# Registered command capabilities are independent of which immutable workflow
# versions currently bind them.
SHARED_WORKFLOW_ENTRYPOINTS = {
    "/yoke idea",
    "/yoke refine",
    "/yoke implement",
    "/yoke polish",
    "/yoke usher",
}

SHARED_WORKFLOW_DOWNSTREAM_PATHS = {
    "shepherd",
    "refine",
    "implement",
    "polish",
    "usher",
}


@pytest.fixture(scope="module")
def codex_manifest() -> dict:
    return json.loads(_read(HARNESS / "codex" / "manifest.json"))


class TestSharedRegistryAdvertisesImplement:
    """The shared registry must list ``/yoke implement`` so capability truth
    aligns with registered workflow skill bindings."""

    def test_implement_in_entrypoints(self):
        entrypoints = shared_entrypoints()
        assert "/yoke implement" in entrypoints, (
            "shared registry must advertise /yoke implement as an entrypoint"
        )

    def test_implement_in_downstream_paths(self):
        paths = shared_downstream_paths()
        assert "implement" in paths, (
            "shared registry must advertise 'implement' as a downstream path"
        )

    def test_registered_workflow_commands_in_entrypoints(self):
        entrypoints = set(shared_entrypoints())
        missing = SHARED_WORKFLOW_ENTRYPOINTS - entrypoints
        assert not missing, (
            f"shared registry is missing workflow entrypoints: {missing}"
        )

    def test_registered_workflow_commands_in_downstream_paths(self):
        paths = set(shared_downstream_paths())
        missing = SHARED_WORKFLOW_DOWNSTREAM_PATHS - paths
        assert not missing, (
            f"shared registry is missing workflow downstream paths: {missing}"
        )

    def test_codex_manifest_does_not_copy_command_truth(self, codex_manifest):
        supports = codex_manifest.get("supports", {})
        assert supports.get("command_source") == "shared_yoke_registry"
        assert "entrypoints" not in supports
        assert "downstream_paths" not in supports


def test_operator_commands_resolve_to_existing_skills():
    from yoke_core.domain.harness_capability_registry import safe_operator_surface

    for command in safe_operator_surface():
        skill_id = command.entrypoint.split()[-1]
        assert (REPO / ".agents/skills/yoke" / skill_id / "SKILL.md").is_file()
        packaged = REPO / "packages/yoke-core/src/yoke_core/install_bundle_tree"
        assert (packaged / ".agents/skills/yoke" / skill_id / "SKILL.md").is_file()
