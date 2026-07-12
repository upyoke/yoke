"""Disconnect behavior for externally owned GitHub refresh credentials."""

from __future__ import annotations

from runtime.api.cli.test_github_machine_credential_cleanup import _config
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import github_machine


def test_disconnect_forgets_external_ref_without_deleting_file(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    external = tmp_path / "operator-refresh.json"
    external.write_text("operator-owned", encoding="utf-8")
    config = home / "config.json"
    _config(config, external)

    report = github_machine.disconnect(config_path=config)

    assert external.read_text(encoding="utf-8") == "operator-owned"
    assert report["configured"] is False
    assert report["credential_removed"] is False
    assert report["ok"] is True
    assert [item["code"] for item in report["issues"]] == [
        "github_external_credential_left_untouched"
    ]


def test_disconnect_cli_succeeds_with_external_credential_warning(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    external = tmp_path / "operator-refresh.json"
    external.write_text("operator-owned", encoding="utf-8")
    config = home / "config.json"
    _config(config, external)

    rc = yoke_operations_cli.main(
        [
            "github",
            "disconnect",
            "--config",
            str(config),
        ]
    )

    assert rc == 0
    assert external.read_text(encoding="utf-8") == "operator-owned"
    assert "left untouched" in capsys.readouterr().err
