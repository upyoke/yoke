"""HC-launcher-authority: login-shell yoke must be the canonical shim."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.engines.doctor_hc_launcher_authority import (
    SLUG,
    hc_launcher_authority,
)


class _Rec:
    def __init__(self) -> None:
        self.rows = []

    def record(self, slug, title, status, detail) -> None:
        self.rows.append((slug, status, detail))


def test_hc_fails_when_login_shell_misses_canonical(monkeypatch, tmp_path: Path) -> None:
    canon = tmp_path / "yoke"
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.canonical_shim_path",
        lambda: canon,
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._login_shell_yoke",
        lambda: str(tmp_path / "other"),
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.enumerate_shadow_installs",
        lambda **kw: [],
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.shutil.which",
        lambda _name: str(tmp_path / "other"),
    )
    rec = _Rec()
    hc_launcher_authority(None, SimpleNamespace(fix=False), rec)
    assert rec.rows[0][0] == SLUG
    assert rec.rows[0][1] == "FAIL"
    assert "not canonical" in rec.rows[0][2]


def test_hc_passes_when_login_matches_canonical(monkeypatch, tmp_path: Path) -> None:
    canon = tmp_path / "yoke"
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.canonical_shim_path",
        lambda: canon,
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._login_shell_yoke",
        lambda: str(canon),
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.enumerate_shadow_installs",
        lambda **kw: [],
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.shutil.which",
        lambda _name: str(canon),
    )
    rec = _Rec()
    hc_launcher_authority(None, SimpleNamespace(fix=False), rec)
    assert rec.rows[0][1] == "PASS"


def test_hc_fix_calls_converge_machine(monkeypatch, tmp_path: Path) -> None:
    called = {}
    canon = tmp_path / "yoke"
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.canonical_shim_path",
        lambda: canon,
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._resolve_checkout",
        lambda _args: tmp_path,
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.converge_machine",
        lambda checkout, stream=None: called.setdefault("checkout", checkout),
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._login_shell_yoke",
        lambda: str(canon),
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.enumerate_shadow_installs",
        lambda **kw: [],
    )
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority.shutil.which",
        lambda _name: str(canon),
    )
    rec = _Rec()
    hc_launcher_authority(None, SimpleNamespace(fix=True), rec)
    assert called["checkout"] == tmp_path
