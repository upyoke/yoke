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
import subprocess
from pathlib import Path

import pytest

from yoke_cli.project_install.files import prune_files
from yoke_cli.project_install.install_recovery import plan
from yoke_cli.project_install.released_bundle_files import ReleasedBundleFiles
from yoke_core.domain.agents_render import AGENTS
from yoke_core.hooks.bootstrap import load_spec


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
    assert set(bootstrap_spec["canonical_agents"]["agents"]) == set(AGENTS)
    assert "qa-walker" not in AGENTS


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



@pytest.mark.parametrize(
    "rel",
    (
        ".claude/agents/yoke-qa-walker.md",
        ".codex/agents/yoke-qa-walker.toml",
        ".cursor/agents/yoke-qa-walker.md",
    ),
)
def test_install_recovery_prunes_only_proven_retired_adapters(tmp_path, monkeypatch, rel):
    monkeypatch.setattr(
        ReleasedBundleFiles, "proves",
        lambda self, path, content: path == rel and content == "released adapter",
    )
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text("local agent", encoding="utf-8")
    result = plan(tmp_path, {"files": []}, {})
    assert prune_files(tmp_path, result["prior_files"], ())[0] == []
    assert target.read_text(encoding="utf-8") == "local agent"

    target.write_text("released adapter", encoding="utf-8")
    result = plan(tmp_path, {"files": []}, {})
    assert prune_files(tmp_path, result["prior_files"], ())[0] == [rel]
    assert not target.exists()


def test_retired_role_has_no_live_definition_or_teaching_reference():
    result = subprocess.run(
        [
            "git", "grep", "-inE", "qa-walker|qa_walker_agent|QA Walker", "--",
            "README.md", "docs", "packages", "runtime", ".yoke/doctor",
            ":!docs/repairs", ":!docs/archive", ":!**/test_*.py",
            ":!**/released_bundle_files.py", ":!**/released_bundle_hashes.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
