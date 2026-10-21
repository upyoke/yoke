"""Direct PATH repair checks every installed supported shell context."""

from types import SimpleNamespace

from yoke_cli.commands.adapters import path_doctor as adapter
from yoke_cli.config.path_doctor import ToolResolution


def test_path_fix_repairs_once_and_verifies_all_contexts(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        adapter.doctor, "update_shell", lambda: calls.append("repair") or "updated"
    )
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda: [ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    monkeypatch.setattr(
        adapter.doctor,
        "diagnose",
        lambda: SimpleNamespace(needs_fix=False, login_needs_fix=False, contexts=()),
    )
    assert adapter.path_fix(["--yes", "--json"]) == 0
    assert calls == ["repair"]
    assert '"verified": true' in capsys.readouterr().out


def test_path_fix_refuses_failed_non_login_probe(monkeypatch, capsys):
    monkeypatch.setattr(adapter.doctor, "update_shell", lambda: "updated")
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda: [ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    monkeypatch.setattr(
        adapter.doctor,
        "diagnose",
        lambda: SimpleNamespace(needs_fix=True, login_needs_fix=False, contexts=()),
    )
    assert adapter.path_fix(["--yes"]) == 1
    assert "shell_path_unresolved" in capsys.readouterr().out
