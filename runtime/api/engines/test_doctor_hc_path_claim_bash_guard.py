"""Tests for HC-path-claim-bash-guard."""

from __future__ import annotations

import json

import pytest

from yoke_core.engines import doctor_hc_path_claim_bash_guard as mod
from yoke_core.engines.doctor_hc_path_claim_bash_guard import (
    hc_path_claim_bash_guard,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn():
    """The HC under test inspects hook configs only; it never reads *conn*."""
    return None


def _record(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_path_claim_bash_guard(conn, DoctorArgs(), rec)
    return rec


def _settings_with_hook_cli(delegated: bool):
    """Rendered hook config; PreToolUse@Bash delegates to hook CLI when ``delegated``."""
    command = (
        "yoke hook evaluate PreToolUse"
        if delegated
        else "python3 -m yoke_core.domain.lint_sqlite_cmd"
    )
    chain = [{"command": command, "type": "command"}]
    return {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": chain}]}}


def _wire_fakes(monkeypatch, tmp_path, *, claude_ok=True, codex_ok=True, chain_ok=True,
                smoke=(True, "deny narratives matched")):
    monkeypatch.setattr(mod, "_guard_module_available", lambda: True)
    monkeypatch.setattr(mod, "_chain_has_guard", lambda: chain_ok)
    monkeypatch.setattr(mod, "_run_guard_smoke", lambda: smoke)
    claude = tmp_path / "claude.json"
    codex = tmp_path / "codex.json"
    claude.write_text(json.dumps(_settings_with_hook_cli(claude_ok)))
    codex.write_text(json.dumps(_settings_with_hook_cli(codex_ok)))

    def fake_root(rel):
        return claude if "claude" in str(rel) else codex

    monkeypatch.setattr(mod, "_root_path", fake_root)


def test_pass_when_guard_module_unavailable(monkeypatch, conn):
    """Substrate-absent PASS-with-note matches the hc_path_integrity precedent."""
    monkeypatch.setattr(mod, "_guard_module_available", lambda: False)
    rec = _record(conn)
    assert rec.results[0].result == "PASS"
    assert "not yet provisioned" in rec.results[0].detail


def test_pass_when_both_chains_delegate_and_registry_lists_guard(monkeypatch, tmp_path, conn):
    _wire_fakes(monkeypatch, tmp_path)
    rec = _record(conn)
    assert rec.results[0].result == "PASS", rec.results[0].detail
    detail = rec.results[0].detail
    assert "claude" in detail
    assert "codex" in detail
    assert "chain_registry" in detail


def test_fail_when_claude_chain_does_not_delegate(monkeypatch, tmp_path, conn):
    _wire_fakes(monkeypatch, tmp_path, claude_ok=False)
    rec = _record(conn)
    assert rec.results[0].result == "FAIL"
    assert "claude: PreToolUse@Bash does not delegate" in rec.results[0].detail


def test_fail_when_codex_chain_does_not_delegate(monkeypatch, tmp_path, conn):
    _wire_fakes(monkeypatch, tmp_path, codex_ok=False)
    rec = _record(conn)
    assert rec.results[0].result == "FAIL"
    assert "codex: PreToolUse@Bash does not delegate" in rec.results[0].detail


def test_fail_when_chain_registry_missing_guard(monkeypatch, tmp_path, conn):
    _wire_fakes(monkeypatch, tmp_path, chain_ok=False)
    rec = _record(conn)
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "chain_registry" in detail
    assert "absent" in detail


def test_fail_when_smoke_misses_narratives(monkeypatch, tmp_path, conn):
    _wire_fakes(
        monkeypatch, tmp_path,
        smoke=(False, "deny smoke output missed: out_of_claim=False"),
    )
    rec = _record(conn)
    assert rec.results[0].result == "FAIL"
    assert "missed" in rec.results[0].detail


def test_fail_when_hook_config_missing(monkeypatch, tmp_path, conn):
    monkeypatch.setattr(mod, "_guard_module_available", lambda: True)
    monkeypatch.setattr(mod, "_chain_has_guard", lambda: True)
    monkeypatch.setattr(mod, "_root_path", lambda rel: tmp_path / "absent.json")
    monkeypatch.setattr(mod, "_run_guard_smoke", lambda: (True, "ok"))
    rec = _record(conn)
    assert rec.results[0].result == "FAIL"
    assert "missing" in rec.results[0].detail


def test_chain_registry_lookup_lists_guard():
    """The chain registry is the authoritative chain composition source."""
    from yoke_contracts.hook_runner.chain_registry import chain_for

    chain = chain_for("PreToolUse", "Bash")
    assert "yoke_core.domain.path_claim_bash_guard" in chain
    assert mod._chain_has_guard() is True


def test_smoke_uses_current_evaluate_payload_signature():
    """The real smoke must succeed against the current evaluate_payload signature."""
    ok, detail = mod._run_guard_smoke()
    assert ok, detail


def test_hc_passes_against_production_hook_configs(conn):
    """End-to-end: the HC must report PASS against the actual rendered hook configs and chain registry."""
    rec = RecordCollector()
    hc_path_claim_bash_guard(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS", rec.results[0].detail
