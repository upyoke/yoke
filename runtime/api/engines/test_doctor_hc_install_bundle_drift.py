"""Tests for HC-install-bundle-drift."""

from __future__ import annotations

from yoke_core.domain import install_bundle_tree_sync
from yoke_core.engines import doctor_hc_install_bundle_drift as hc_mod
from yoke_core.engines.doctor_hc_install_bundle_drift import (
    hc_install_bundle_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run() -> RecordCollector:
    rec = RecordCollector()
    hc_install_bundle_drift(None, DoctorArgs(), rec)
    return rec


def _make_checkout(tmp_path):
    """A tmp root whose packaged install-bundle tree dir exists."""
    (tmp_path / install_bundle_tree_sync.PACKAGED_TREE_REL).mkdir(parents=True)
    return tmp_path


def test_pass_when_snapshot_in_sync(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(hc_mod, "_resolve_repo_root", lambda: str(root))
    monkeypatch.setattr(
        install_bundle_tree_sync, "detect_drift", lambda *, target_root: []
    )
    rec = _run()
    assert rec.results[0].result == "PASS"
    assert "byte-matches" in rec.results[0].detail


def test_fail_when_snapshot_drifts(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(hc_mod, "_resolve_repo_root", lambda: str(root))
    monkeypatch.setattr(
        install_bundle_tree_sync,
        "detect_drift",
        lambda *, target_root: [
            "content drift: runtime/harness/codex/agents/yoke-boss.toml",
        ],
    )
    rec = _run()
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "yoke-boss.toml" in detail
    assert "install_bundle_tree_sync sync" in detail


def test_pass_when_no_packaged_tree_in_checkout(tmp_path, monkeypatch):
    # No PACKAGED_TREE_REL dir created — a checkout that ships no snapshot.
    monkeypatch.setattr(hc_mod, "_resolve_repo_root", lambda: str(tmp_path))
    rec = _run()
    assert rec.results[0].result == "PASS"
    assert "not applicable" in rec.results[0].detail


def test_pass_when_repo_root_unresolvable(monkeypatch):
    monkeypatch.setattr(hc_mod, "_resolve_repo_root", lambda: None)
    rec = _run()
    assert rec.results[0].result == "PASS"
    assert "skipped" in rec.results[0].detail


def test_fail_when_detector_raises(tmp_path, monkeypatch):
    root = _make_checkout(tmp_path)
    monkeypatch.setattr(hc_mod, "_resolve_repo_root", lambda: str(root))

    def boom(*, target_root):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(install_bundle_tree_sync, "detect_drift", boom)
    rec = _run()
    assert rec.results[0].result == "FAIL"
    assert "detector exploded" in rec.results[0].detail
