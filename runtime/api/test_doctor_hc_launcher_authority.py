"""HC-launcher-authority: login-shell yoke must be the canonical shim."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_core.engines.doctor_hc_launcher_authority import (
    SLUG,
    hc_launcher_authority,
    hook_config_yoke_problems,
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
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._resolve_checkout",
        lambda _args: None,
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
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_launcher_authority._resolve_checkout",
        lambda _args: None,
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


def test_hook_config_flags_non_canonical_absolute_yoke(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    (tmp_path / "uv" / "tools").mkdir(parents=True)
    shadow = tmp_path / "uv" / "tools" / "yoke"
    shadow.write_text("shadow\n")
    settings.write_text(
        json.dumps({
            "hooks": {
                "PreToolUse": [{
                    "hooks": [{"command": f"{shadow} hook evaluate PreToolUse"}],
                }],
            },
        }),
        encoding="utf-8",
    )
    canon = tmp_path / "canonical" / "yoke"
    canon.parent.mkdir()
    canon.write_text("canon\n")
    problems = hook_config_yoke_problems(tmp_path, canon)
    assert problems
    assert "not canonical" in problems[0]


def test_hook_config_accepts_bare_yoke_command(tmp_path: Path) -> None:
    settings = tmp_path / ".cursor" / "hooks.json"
    settings.parent.mkdir()
    settings.write_text(
        '{"version":1,"hooks":{"sessionStart":[{"command":"/bin/zsh -lc \'yoke hook evaluate SessionStart\'"}]}}',
        encoding="utf-8",
    )
    canon = tmp_path / "yoke"
    canon.write_text("canon\n")
    assert hook_config_yoke_problems(tmp_path, canon) == []
