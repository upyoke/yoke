"""Tests for HC-gate-liveness (pre-commit gate liveness).

Covers: PASS when the effective .git/hooks/pre-commit carries the Yoke marker,
WARN when it is foreign or missing, WARN when core.hooksPath shadows the gate
with a foreign hook, PASS when core.hooksPath points at a dir whose pre-commit
IS the Yoke shim, and silent SKIP when the checkout is not a git repo or the
repo root cannot be resolved.
"""

from __future__ import annotations

from pathlib import Path

import yoke_core.engines.doctor_report as _base
from yoke_contracts.git_hook_markers import PRE_COMMIT_MARKER
from yoke_core.engines import doctor_hc_gate_liveness as gl
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _shim_body() -> str:
    return (
        "#!/bin/sh\n"
        f"# {PRE_COMMIT_MARKER} hook installed by `yoke project install`\n"
        'exec yoke git pre-commit "$@"\n'
    )


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git" / "hooks").mkdir(parents=True)
    return root


def _record(monkeypatch, root, core_hooks_path) -> RecordCollector:
    monkeypatch.setattr(
        _base, "_resolve_repo_root",
        lambda: str(root) if root is not None else None,
    )
    monkeypatch.setattr(gl, "_core_hooks_path", lambda r: core_hooks_path)
    rec = RecordCollector()
    gl.hc_gate_liveness(None, DoctorArgs(), rec)
    return rec


def test_pass_when_shim_marker_present(tmp_path, monkeypatch) -> None:
    root = _git_repo(tmp_path)
    (root / ".git" / "hooks" / "pre-commit").write_text(
        _shim_body(), encoding="utf-8",
    )
    rec = _record(monkeypatch, root, None)
    assert rec.results[0].result == "PASS"
    assert rec.results[0].check_id == gl.CHECK_ID


def test_warn_when_pre_commit_missing(tmp_path, monkeypatch) -> None:
    root = _git_repo(tmp_path)  # hooks dir exists, no pre-commit file
    rec = _record(monkeypatch, root, None)
    assert rec.results[0].result == "WARN"
    assert "not active" in rec.results[0].detail


def test_warn_when_pre_commit_foreign(tmp_path, monkeypatch) -> None:
    root = _git_repo(tmp_path)
    (root / ".git" / "hooks" / "pre-commit").write_text(
        "#!/bin/sh\nexec /custom/gate\n", encoding="utf-8",
    )
    rec = _record(monkeypatch, root, None)
    assert rec.results[0].result == "WARN"
    assert "not active" in rec.results[0].detail


def test_warn_when_core_hooks_path_shadows(tmp_path, monkeypatch) -> None:
    root = _git_repo(tmp_path)
    # The default hook IS the Yoke shim, but core.hooksPath points elsewhere
    # at a foreign hook — the gate looks installed yet never runs.
    (root / ".git" / "hooks" / "pre-commit").write_text(
        _shim_body(), encoding="utf-8",
    )
    other = tmp_path / "other-hooks"
    other.mkdir()
    (other / "pre-commit").write_text(
        "#!/bin/sh\nexec /custom/gate\n", encoding="utf-8",
    )
    rec = _record(monkeypatch, root, str(other))
    assert rec.results[0].result == "WARN"
    assert "core.hooksPath shadows" in rec.results[0].detail


def test_pass_when_core_hooks_path_points_at_shim(tmp_path, monkeypatch) -> None:
    root = _git_repo(tmp_path)
    other = tmp_path / "custom-hooks"
    other.mkdir()
    (other / "pre-commit").write_text(_shim_body(), encoding="utf-8")
    rec = _record(monkeypatch, root, str(other))
    assert rec.results[0].result == "PASS"


def test_skip_when_not_a_git_repo(tmp_path, monkeypatch) -> None:
    root = tmp_path / "plain"
    root.mkdir()  # no .git
    rec = _record(monkeypatch, root, None)
    assert rec.results == []


def test_skip_when_repo_root_unresolved(monkeypatch) -> None:
    rec = _record(monkeypatch, None, None)
    assert rec.results == []
