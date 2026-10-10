"""HC-launcher-authority: login-shell yoke must be the canonical shim."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_hc_fails_when_login_shell_misses_canonical(
    monkeypatch, tmp_path: Path
) -> None:
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
        lambda _name, path=None: str(tmp_path / "other"),
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
        lambda _name, path=None: str(canon),
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
        lambda _name, path=None: str(canon),
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
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {"command": f"{shadow} hook evaluate PreToolUse"}
                            ],
                        }
                    ],
                },
            }
        ),
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


@pytest.mark.parametrize("shell", ["/usr/bin/fish", None])
def test_login_shell_uses_configured_shell_or_posix_fallback(monkeypatch, shell):
    from subprocess import CompletedProcess
    from yoke_core.engines import doctor_hc_launcher_authority as check

    calls = []
    if shell is None:
        monkeypatch.delenv("SHELL", raising=False)
    else:
        monkeypatch.setenv("SHELL", shell)

    def run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, "/tmp/bin/yoke\n", "")

    monkeypatch.setattr(check.subprocess, "run", run)
    assert check._login_shell_yoke() == "/tmp/bin/yoke"
    assert calls == [[shell or "/bin/sh", "-lc", "command -v yoke"]]


@pytest.mark.parametrize("verified_source", [True, False])
def test_launcher_probe_preserves_unrelated_path_shadows(
    monkeypatch, tmp_path, verified_source
):
    from yoke_core.engines import doctor_hc_launcher_authority as check

    source = tmp_path / "source"
    source_bin = source / ".venv" / "bin"
    other_bin = tmp_path / "other" / "bin"
    machine_bin = tmp_path / "machine" / "bin"
    original = check.os.pathsep.join(map(str, (source_bin, other_bin, machine_bin)))
    monkeypatch.setenv("PATH", original)
    monkeypatch.setenv(check.SOURCE_DEV_RUN_ROOT_ENV, str(source))
    prefix = source / ".venv" if verified_source else tmp_path / "unrelated"
    monkeypatch.setattr(check.sys, "prefix", str(prefix))

    observed = check._machine_launcher_env()["PATH"]
    expected = (
        check.os.pathsep.join(map(str, (other_bin, machine_bin)))
        if verified_source else original
    )
    assert observed == expected


def test_ordinary_venv_activation_remains_in_machine_probe(monkeypatch, tmp_path):
    from yoke_core.engines import doctor_hc_launcher_authority as check

    activated_bin = tmp_path / ".venv" / "bin"
    monkeypatch.setenv("PATH", str(activated_bin))
    monkeypatch.setattr(check.sys, "prefix", str(activated_bin.parent))
    monkeypatch.delenv(check.SOURCE_DEV_RUN_ROOT_ENV, raising=False)
    assert check._machine_launcher_env()["PATH"] == str(activated_bin)
