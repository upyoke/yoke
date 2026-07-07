"""Tests for HC-codex-agent-adapter-drift and HC-codex-subagent-surface-truth."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.engines import doctor_hc_codex_agent as mod
from yoke_core.engines.doctor_hc_codex_agent import (
    _CANONICAL_AGENTS,
    hc_codex_agent_adapter_drift,
    hc_codex_subagent_surface_truth,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _record(fn, conn) -> RecordCollector:
    rec = RecordCollector()
    fn(conn, DoctorArgs(), rec)
    return rec


# ---------------------------------------------------------------------------
# Adapter-drift HC
# ---------------------------------------------------------------------------


def _make_adapter_tree(tmp_path: Path, *, with_drift=False, missing_role=None,
                       extra_file=False) -> Path:
    """Build a fake repo with canonical bodies and Codex adapters."""
    canonical = tmp_path / "runtime/agents"
    codex = tmp_path / ".codex/agents"
    canonical.mkdir(parents=True)
    codex.mkdir(parents=True)
    for agent in _CANONICAL_AGENTS:
        (canonical / f"{agent}.md").write_text(
            f"# canonical body for {agent}\n", encoding="utf-8",
        )
        if missing_role == agent:
            continue
        adapter_text = f"prefix\n# canonical body for {agent}\nsuffix\n"
        if with_drift and agent == "engineer":
            adapter_text = "# completely different body\n"
        (codex / f"yoke-{agent}.toml").write_text(adapter_text, encoding="utf-8")
    if extra_file:
        (codex / "yoke-rogue.toml").write_text("rogue\n", encoding="utf-8")
    return tmp_path


def test_adapter_drift_pass_with_provisioned_clean_tree(monkeypatch, tmp_path, conn):
    root = _make_adapter_tree(tmp_path)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "PASS"


def test_adapter_drift_pass_when_codex_dir_missing(monkeypatch, tmp_path, conn):
    """Substrate-absent PASS-with-note matches the hc_path_integrity precedent."""
    monkeypatch.setattr(mod, "_root_path", lambda rel: tmp_path / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "PASS"
    assert "not provisioned" in rec.results[0].detail


def test_adapter_drift_fail_on_canonical_drift(monkeypatch, tmp_path, conn):
    root = _make_adapter_tree(tmp_path, with_drift=True)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "FAIL"
    assert "engineer" in rec.results[0].detail


def test_adapter_drift_fail_on_missing_adapter(monkeypatch, tmp_path, conn):
    root = _make_adapter_tree(tmp_path, missing_role="tester")
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "FAIL"
    assert "tester" in rec.results[0].detail


def test_adapter_drift_fail_on_unexpected_extra_file(monkeypatch, tmp_path, conn):
    root = _make_adapter_tree(tmp_path, extra_file=True)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "FAIL"
    assert "yoke-rogue.toml" in rec.results[0].detail


def test_adapter_drift_picks_up_per_role_subdir_fragments(monkeypatch, tmp_path, conn):
    """Per-role subdir fragments must be embedded in the adapter too."""
    root = _make_adapter_tree(tmp_path)
    # Add a subdir fragment for engineer; adapter must contain it.
    sub = root / "runtime/agents/engineer"
    sub.mkdir()
    (sub / "fragment.md").write_text("supplemental engineer text\n", encoding="utf-8")
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    # The adapter doesn't include the supplemental text → drift.
    assert rec.results[0].result == "FAIL"
    assert "engineer" in rec.results[0].detail


def test_adapter_drift_fail_on_stale_schema_residue(monkeypatch, tmp_path, conn):
    """AC-10: an adapter carrying the retired schema (prompt / string tools /
    max_turns / model="opus") fails the HC even when its canonical body is
    present — the schema-residue scan is independent of byte parity."""
    root = _make_adapter_tree(tmp_path)
    # Keep the canonical body so the parity/drift path passes; the only
    # failure signal is the retired schema fields.
    stale = (
        'name = "yoke-engineer"\n'
        'model = "opus"\n'
        'tools = "Read, Write"\n'
        'max_turns = 120\n'
        'prompt = """\n# canonical body for engineer\n"""\n'
    )
    (root / ".codex/agents/yoke-engineer.toml").write_text(stale, encoding="utf-8")
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_agent_adapter_drift, conn)
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "stale Codex adapter schema" in detail
    assert "yoke-engineer.toml" in detail


# ---------------------------------------------------------------------------
# Surface-truth HC
# ---------------------------------------------------------------------------


def _make_final_surface_root(tmp_path: Path, *, codex_disabled=False,
                             claude_disabled=False, docs_supported=True,
                             docs_unsupported=False) -> Path:
    root = tmp_path
    (root / "runtime/harness/claude").mkdir(parents=True)
    (root / "runtime/harness/codex").mkdir(parents=True)
    (root / "docs").mkdir()
    codex_disabled_entrypoints = '["/yoke conduct"]' if codex_disabled else "[]"
    claude_disabled_entrypoints = '["/yoke conduct"]' if claude_disabled else "[]"
    (root / "runtime/harness/codex/manifest.json").write_text(
        '{"supports": {"disabled_entrypoints": ' + codex_disabled_entrypoints + "}}",
        encoding="utf-8",
    )
    (root / "runtime/harness/claude/manifest.json").write_text(
        '{"supports": {"disabled_entrypoints": ' + claude_disabled_entrypoints + "}}",
        encoding="utf-8",
    )

    if docs_supported:
        codex_doc = "Codex covers the full Tier 1 surface, including `/yoke conduct`."
        agents_doc = "Codex dispatches conduct through generated custom agents."
    elif docs_unsupported:
        codex_doc = "Codex has no equivalent sub-agent dispatch for conduct."
        agents_doc = "Conduct is Claude-Code only."
    else:
        codex_doc = "Codex covers polish and usher."
        agents_doc = "Agents use canonical bodies."
    (root / "CODEX.md").write_text(codex_doc, encoding="utf-8")
    (root / "docs/agents.md").write_text(agents_doc, encoding="utf-8")
    return root


def test_surface_truth_pass_with_final_dual_harness_surfaces(monkeypatch, tmp_path, conn):
    """Final truth says conduct is supported by both harnesses."""
    root = _make_final_surface_root(tmp_path)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "PASS"
    assert "claude=True" in rec.results[0].detail
    assert "codex=True" in rec.results[0].detail


def test_surface_truth_fail_when_registry_says_codex_unsupported(monkeypatch, tmp_path, conn):
    root = _make_final_surface_root(tmp_path)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    monkeypatch.setattr(mod, "_codex_supports_conduct", lambda: False)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "dual-harness conduct support" in rec.results[0].detail


def test_surface_truth_fail_when_conduct_missing_from_registry(monkeypatch, conn):
    monkeypatch.setattr(mod, "_claude_supports_conduct", lambda: None)
    monkeypatch.setattr(mod, "_codex_supports_conduct", lambda: None)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "missing" in rec.results[0].detail


def test_surface_truth_fail_when_codex_manifest_disables_conduct(monkeypatch, tmp_path, conn):
    root = _make_final_surface_root(tmp_path, codex_disabled=True)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "Codex manifest disables" in rec.results[0].detail


def test_surface_truth_fail_when_claude_manifest_disables_conduct(monkeypatch, tmp_path, conn):
    root = _make_final_surface_root(tmp_path, claude_disabled=True)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "Claude manifest disables" in rec.results[0].detail


def test_surface_truth_fail_when_docs_still_say_codex_unsupported(monkeypatch, tmp_path, conn):
    root = _make_final_surface_root(
        tmp_path, docs_supported=False, docs_unsupported=True,
    )
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "unsupported" in rec.results[0].detail


def test_surface_truth_fail_when_docs_omit_codex_support(monkeypatch, tmp_path, conn):
    root = _make_final_surface_root(tmp_path, docs_supported=False)
    monkeypatch.setattr(mod, "_root_path", lambda rel: root / rel)
    rec = _record(hc_codex_subagent_surface_truth, conn)
    assert rec.results[0].result == "FAIL"
    assert "do not state Codex conduct support" in rec.results[0].detail
