"""CLI integration tests for manifest-backed drift surfacing."""

from __future__ import annotations

from yoke_cli import main as yoke_operations_cli
from yoke_cli.manifest import build_manifest


def _manifest_with_extra() -> dict:
    manifest = build_manifest()
    manifest["subcommands"].append({
        "tokens": ["zz", "top"], "function_id": "zz.top.run",
        "usage": "yoke zz top --afterburner",
        "help_label": "source-dev/admin",
    })
    return manifest


def test_unknown_subcommand_names_cli_update_when_env_serves_it(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda allow_fetch=True: _manifest_with_extra(),
    )

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "rerun the public installer" in err
    assert "zz.top.run" in err
    assert "subcommand [source-dev/admin]" in err
    assert "yoke zz top --afterburner" in err


def test_unknown_subcommand_without_manifest_keeps_plain_error(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda allow_fetch=True: None,
    )

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "Run `yoke --help`" in err
    assert "rerun the public installer" not in err


def test_help_appends_server_only_drift_section(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda allow_fetch=True: _manifest_with_extra(),
    )

    rc = yoke_operations_cli.main(["--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Active env manifest:" in out
    assert "Server-only subcommands" in out
    assert "yoke zz top [source-dev/admin] -> zz.top.run" in out


def test_help_renders_without_manifest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda allow_fetch=True: None,
    )

    rc = yoke_operations_cli.main(["--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Active env manifest:" not in out
