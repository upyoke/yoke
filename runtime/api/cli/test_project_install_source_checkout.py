"""Source-checkout boundaries for ``yoke project install``."""

from __future__ import annotations

import pytest

from yoke_cli import main as yoke_operations_cli


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return tmp_path / "machine-home" / "config.json"


@pytest.fixture()
def source_checkout(tmp_path):
    root = tmp_path / "yoke-src"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n', encoding="utf-8")
    (root / "runtime" / "harness").mkdir(parents=True)
    return root


def test_install_source_checkout_hands_off_to_dev_setup(
    cfg, source_checkout, capsys
) -> None:
    rc = yoke_operations_cli.main(
        ["project", "install", str(source_checkout), "--config", str(cfg)]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "yoke dev setup" in captured.err
    assert "source-link" in captured.err
    assert not (source_checkout / ".claude" / "agents").exists()
    assert not (source_checkout / ".yoke/install-manifest.json").exists()


def test_source_checkout_refusal_is_repeatable(cfg, source_checkout, capsys) -> None:
    rc = yoke_operations_cli.main(
        ["project", "install", str(source_checkout), "--config", str(cfg)]
    )
    assert rc == 1
    assert "yoke dev setup" in capsys.readouterr().err


def test_project_install_help_does_not_advertise_source_dev_modes(capsys) -> None:
    assert yoke_operations_cli.main(["project", "install", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--source-link" not in out
    assert "source-link" not in out
    assert "source-dev" not in out


def test_project_refresh_help_labels_source_dev_preview_and_apply(capsys) -> None:
    assert yoke_operations_cli.main(["project", "refresh", "--help"]) == 0
    out = capsys.readouterr().out
    assert "source-dev/admin local-source refresh" in out
    assert "--source-checkout PATH" in out
    assert "--project-slug SLUG" in out
    assert "--manifest-from PATH" in out
    assert "--apply" in out
    assert "Preview-only unless --apply" in out
