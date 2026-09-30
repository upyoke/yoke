"""Direct PATH repair delegates to uv and verifies actual shell state."""

from yoke_cli.commands.adapters import path_doctor as adapter
from yoke_cli.config.path_doctor import ToolResolution


def test_path_fix_delegates_once_and_verifies(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        adapter.doctor,
        "update_shell",
        lambda: calls.append("uv tool update-shell") or "updated",
    )
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda: [ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    assert adapter.path_fix(["--yes", "--json"]) == 0
    assert calls == ["uv tool update-shell"]
    assert '"login_verified": true' in capsys.readouterr().out


def test_path_fix_refuses_failed_login_probe(monkeypatch, capsys):
    monkeypatch.setattr(adapter.doctor, "update_shell", lambda: "updated")
    monkeypatch.setattr(adapter.doctor, "verify_fresh_login", lambda: [])
    assert adapter.path_fix(["--yes"]) == 1
    assert "fresh_login_path_unresolved" in capsys.readouterr().out
