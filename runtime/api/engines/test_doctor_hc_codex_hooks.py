"""Tests for the Codex hook HC bundle.

Covers HC-codex-hook-matchers, HC-codex-hook-floor, HC-codex-hook-doc-drift.
Each HC is exercised on its happy path and at least one drift/failure path.
The apply-patch smoke HCs live in ``test_doctor_hc_apply_patch``.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.engines import doctor_hc_codex_hooks as mod
from yoke_core.engines.doctor_hc_codex_hooks import (
    _REQUIRED_HOOK_PAIRS,
    _semver_tuple,
    hc_codex_hook_doc_drift,
    hc_codex_hook_floor,
    hc_codex_hook_matchers,
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


def _hooks_doc(pairs):
    """Build a hooks.json doc that satisfies *pairs*."""
    out: dict = {"hooks": {}}
    for event, matcher in pairs:
        entry = {"hooks": [{"type": "command", "command": "noop"}]}
        if matcher:
            entry["matcher"] = matcher
        out["hooks"].setdefault(event, []).append(entry)
    return out


# ---------------------------------------------------------------------------
# HC-codex-hook-matchers
# ---------------------------------------------------------------------------


def test_matchers_pass_with_full_set(monkeypatch, tmp_path, conn):
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps(_hooks_doc(_REQUIRED_HOOK_PAIRS)))
    monkeypatch.setattr(mod, "_hooks_path", lambda: target)
    rec = _record(hc_codex_hook_matchers, conn)
    assert rec.results[0].result == "PASS"


def test_matchers_fail_on_missing_pretool_bash(monkeypatch, tmp_path, conn):
    pairs = [p for p in _REQUIRED_HOOK_PAIRS if p != ("PreToolUse", "Bash")]
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps(_hooks_doc(pairs)))
    monkeypatch.setattr(mod, "_hooks_path", lambda: target)
    rec = _record(hc_codex_hook_matchers, conn)
    assert rec.results[0].result == "FAIL"
    assert "PreToolUse@Bash" in rec.results[0].detail


def test_matchers_fail_when_file_missing(monkeypatch, tmp_path, conn):
    monkeypatch.setattr(mod, "_hooks_path", lambda: tmp_path / "nope.json")
    rec = _record(hc_codex_hook_matchers, conn)
    assert rec.results[0].result == "FAIL"
    assert "missing" in rec.results[0].detail


# ---------------------------------------------------------------------------
# HC-codex-hook-floor
# ---------------------------------------------------------------------------


def test_floor_passes_when_installed_meets_floor(monkeypatch, conn):
    monkeypatch.setattr(mod, "_read_floor_token", lambda: "0.118.0-alpha.2")
    monkeypatch.setattr(mod, "_detect_codex_version", lambda: "0.118.0-alpha.5")
    rec = _record(hc_codex_hook_floor, conn)
    assert rec.results[0].result == "PASS"


def test_floor_fails_when_installed_below_floor(monkeypatch, conn):
    monkeypatch.setattr(mod, "_read_floor_token", lambda: "0.118.0-alpha.2")
    monkeypatch.setattr(mod, "_detect_codex_version", lambda: "0.117.5")
    rec = _record(hc_codex_hook_floor, conn)
    assert rec.results[0].result == "FAIL"
    assert "below" in rec.results[0].detail


def test_floor_passes_when_codex_not_installed(monkeypatch, conn):
    monkeypatch.setattr(mod, "_read_floor_token", lambda: "0.118.0-alpha.2")
    monkeypatch.setattr(mod, "_detect_codex_version", lambda: None)
    rec = _record(hc_codex_hook_floor, conn)
    assert rec.results[0].result == "PASS"
    assert "wrapper-only" in rec.results[0].detail


def test_floor_passes_when_manifest_unavailable(monkeypatch, conn):
    monkeypatch.setattr(mod, "_read_floor_token", lambda: None)
    rec = _record(hc_codex_hook_floor, conn)
    assert rec.results[0].result == "PASS"


def test_semver_tuple_orders_pre_release_below_release():
    assert _semver_tuple("0.118.0-alpha.2") < _semver_tuple("0.118.0")
    assert _semver_tuple("0.118.0-alpha.2") < _semver_tuple("0.118.1")
    assert _semver_tuple("0.118.0") < _semver_tuple("0.119.0")


# ---------------------------------------------------------------------------
# HC-codex-hook-doc-drift
# ---------------------------------------------------------------------------


def _write_doc(path, names):
    path.write_text("\n".join(names) + "\n", encoding="utf-8")


def test_doc_drift_pass_when_both_docs_mention_pairs(monkeypatch, tmp_path, conn):
    smoke = tmp_path / "smoke.md"
    parity = tmp_path / "parity.md"
    names = [event for event, _ in _REQUIRED_HOOK_PAIRS]
    _write_doc(smoke, names)
    _write_doc(parity, names)

    def fake_doc_path(rel):
        return smoke if "SMOKE" in str(rel) else parity

    monkeypatch.setattr(mod, "_doc_path", fake_doc_path)
    rec = _record(hc_codex_hook_doc_drift, conn)
    assert rec.results[0].result == "PASS"


def test_doc_drift_fail_when_parity_drops_an_event(monkeypatch, tmp_path, conn):
    smoke = tmp_path / "smoke.md"
    parity = tmp_path / "parity.md"
    names = [event for event, _ in _REQUIRED_HOOK_PAIRS]
    _write_doc(smoke, names)
    _write_doc(parity, names[:-1])  # drop the last event

    def fake_doc_path(rel):
        return smoke if "SMOKE" in str(rel) else parity

    monkeypatch.setattr(mod, "_doc_path", fake_doc_path)
    rec = _record(hc_codex_hook_doc_drift, conn)
    assert rec.results[0].result == "FAIL"
    assert "parity" in rec.results[0].detail or "omits" in rec.results[0].detail


def test_doc_drift_fail_when_doc_files_missing(monkeypatch, tmp_path, conn):
    monkeypatch.setattr(mod, "_doc_path", lambda rel: tmp_path / "nope.md")
    rec = _record(hc_codex_hook_doc_drift, conn)
    assert rec.results[0].result == "FAIL"
