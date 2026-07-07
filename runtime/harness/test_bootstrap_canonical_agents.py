"""Tests for the canonical_agents metadata in bootstrap-spec and Codex manifest.

Validates that:
- bootstrap-spec.json exposes canonical_agents with correct structure
- Every listed agent resolves to a real file under runtime/agents/
- The Codex manifest points back at the bootstrap-spec source
- The manifest declares the canonical_agents tree as generated adapters
- load_spec parses the new key without error
- recommended_files does NOT contain any yoke/agents/*.md paths (bloat guard)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.harness.bootstrap import load_spec


def _repo_root() -> Path:
    """Resolve the repo root (parent of yoke/ directory)."""
    here = Path(__file__).resolve()
    # Walk up to find the repo root (contains AGENTS.md — CLAUDE.md is a
    # compatibility symlink and may be present or absent depending on the
    # checkout). Testing on the real doctrine file keeps the discovery stable.
    candidate = here
    for _ in range(10):
        candidate = candidate.parent
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("Cannot find repo root")


ROOT = _repo_root()
BOOTSTRAP_SPEC_PATH = ROOT / "runtime" / "harness" / "bootstrap-spec.json"
MANIFEST_PATH = ROOT / "runtime" / "harness" / "codex" / "manifest.json"


@pytest.fixture
def bootstrap_spec() -> dict:
    return load_spec(BOOTSTRAP_SPEC_PATH)


@pytest.fixture
def manifest() -> dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_bootstrap_spec_has_canonical_agents_key(bootstrap_spec: dict) -> None:
    assert "canonical_agents" in bootstrap_spec, (
        "bootstrap-spec.json must contain a canonical_agents key"
    )
    ca = bootstrap_spec["canonical_agents"]
    for field in ("root", "agents", "references", "body_suffix", "note"):
        assert field in ca, f"canonical_agents must contain '{field}'"


def test_canonical_agents_root_is_yoke_agents(bootstrap_spec: dict) -> None:
    assert bootstrap_spec["canonical_agents"]["root"] == "runtime/agents"


def test_canonical_agents_paths_resolve(bootstrap_spec: dict) -> None:
    ca = bootstrap_spec["canonical_agents"]
    root_dir = ca["root"]
    suffix = ca["body_suffix"]
    for agent in ca["agents"]:
        agent_path = ROOT / root_dir / f"{agent}{suffix}"
        assert agent_path.is_file(), f"Agent file missing: {agent_path}"
    for ref in ca["references"]:
        ref_path = ROOT / root_dir / f"{ref}{suffix}"
        assert ref_path.is_file(), f"Reference file missing: {ref_path}"


def test_manifest_canonical_agents_points_at_bootstrap(manifest: dict) -> None:
    assert "canonical_agents" in manifest, (
        "codex manifest.json must contain a canonical_agents key"
    )
    ca = manifest["canonical_agents"]
    assert ca["source"] == "runtime/harness/bootstrap-spec.json#canonical_agents"
    assert ca["consumption"] == "generated"


def test_load_spec_accepts_new_key(bootstrap_spec: dict) -> None:
    """load_spec returns the full dict including canonical_agents."""
    assert isinstance(bootstrap_spec["canonical_agents"], dict)
    assert len(bootstrap_spec["canonical_agents"]["agents"]) == 7


def test_recommended_files_no_agents_bloat(bootstrap_spec: dict) -> None:
    """recommended_files must NOT contain any yoke/agents/*.md paths."""
    recommended = bootstrap_spec.get("recommended_files", [])
    agent_paths = [p for p in recommended if p.startswith("runtime/agents/")]
    assert agent_paths == [], (
        f"recommended_files must not contain agent paths (bloat guard): {agent_paths}"
    )
    # Also check required_files for completeness
    required = bootstrap_spec.get("required_files", [])
    agent_in_required = [p for p in required if p.startswith("runtime/agents/")]
    assert agent_in_required == [], (
        f"required_files must not contain agent paths: {agent_in_required}"
    )
