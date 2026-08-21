"""CLI integration tests for manifest-backed drift surfacing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.manifest import build_manifest
from yoke_cli.operating_layer_drift import (
    RUNNING_AHEAD,
    RUNNING_BEHIND,
    RUNNING_DIVERGED,
    RUNNING_EQUAL,
    RUNNING_UNKNOWN,
)


def _manifest_with_extra() -> dict:
    manifest = build_manifest()
    manifest["server_engine_version"] = "0.1.1+launch.246"
    manifest["subcommands"].append(
        {
            "tokens": ["zz", "top"],
            "function_id": "zz.top.run",
            "usage": "yoke zz top --afterburner",
            "help_label": "source-dev/admin",
        }
    )
    return manifest


def _set_running_relationship(monkeypatch, relationship: str) -> None:
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_installed_layer",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_running_to_release",
        lambda *args, **kwargs: SimpleNamespace(
            relationship=relationship,
            source_checkout="",
        ),
    )


def _set_manifest(monkeypatch, manifest=None, *, seen=None) -> None:
    def active_env_manifest(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        return _manifest_with_extra() if manifest is None else manifest

    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        active_env_manifest,
    )


def test_unknown_subcommand_names_cli_update_when_env_serves_it(
    monkeypatch, capsys,
) -> None:
    _set_manifest(monkeypatch)
    _set_running_relationship(monkeypatch, RUNNING_BEHIND)

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "rerun the public installer" in err.lower()
    assert "zz.top.run" in err
    assert "subcommand [source-dev/admin]" in err
    assert "yoke zz top --afterburner" in err


def test_unknown_subcommand_refreshes_stale_project_layer_before_cli(
    monkeypatch,
    capsys,
) -> None:
    _set_manifest(monkeypatch)
    installed = SimpleNamespace(
        layer_is_behind=True,
        receipt=SimpleNamespace(
            source_engine_release="0.1.1+launch.244",
            project_root=Path("/work/demo"),
        ),
    )
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_installed_layer",
        lambda *args, **kwargs: installed,
    )

    def _comparison_must_not_run(*args, **kwargs):
        raise AssertionError("server comparison must follow installed-layer check")

    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_running_to_release",
        _comparison_must_not_run,
    )

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "yoke project install /work/demo" in err
    assert "Do not reinstall the newer CLI/source checkout" in err
    assert "rerun the public installer" not in err.lower()


def test_unknown_subcommand_when_running_cli_is_ahead_waits_for_server(
    monkeypatch,
    capsys,
) -> None:
    _set_manifest(monkeypatch)
    _set_running_relationship(monkeypatch, RUNNING_AHEAD)

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "ahead of the active server release" in err
    assert "Deploy the matching server release or wait" in err
    assert "Do not reinstall the CLI" in err
    assert "public installer" not in err.lower()


@pytest.mark.parametrize(
    ("relationship", "diagnosis"),
    [
        (RUNNING_EQUAL, "compare equal"),
        (RUNNING_DIVERGED, "have diverged"),
        (RUNNING_UNKNOWN, "does not establish which operating layer"),
    ],
)
def test_unknown_subcommand_without_direction_does_not_choose_reinstall(
    monkeypatch,
    capsys,
    relationship,
    diagnosis,
) -> None:
    _set_manifest(monkeypatch)
    _set_running_relationship(monkeypatch, relationship)

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert diagnosis in err
    assert "Do not reinstall the CLI based on this unknown subcommand alone" in err
    assert "rerun the public installer" not in err.lower()
    assert "zz.top.run" in err
    assert "subcommand [source-dev/admin]" in err
    assert "Server usage: yoke zz top --afterburner" in err


def test_unknown_subcommand_without_manifest_keeps_plain_error(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda **kwargs: None,
    )

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "Run `yoke --help`" in err
    assert "rerun the public installer" not in err.lower()


def test_stale_project_layer_is_named_even_when_server_lacks_command(
    monkeypatch, capsys,
) -> None:
    _set_manifest(monkeypatch, build_manifest())
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_installed_layer",
        lambda *args, **kwargs: SimpleNamespace(
            layer_is_behind=True,
            receipt=SimpleNamespace(
                source_engine_release="0.1.1+launch.244",
                project_root=Path("/work/demo"),
            ),
        ),
    )

    rc = yoke_operations_cli.main(["sessions", "init"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "yoke project install /work/demo" in err
    assert "public installer" not in err.lower()


def test_source_checkout_behind_server_uses_git_pull(monkeypatch, capsys) -> None:
    _set_manifest(monkeypatch)
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_installed_layer",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_running_to_release",
        lambda *args, **kwargs: SimpleNamespace(
            relationship=RUNNING_BEHIND,
            source_checkout="/work/yoke source",
        ),
    )

    rc = yoke_operations_cli.main(["zz", "top"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "git -C '/work/yoke source' pull --ff-only" in err
    assert "public installer does not update a source checkout" in err
    assert "rerun the public installer" not in err.lower()


def test_unknown_subcommand_threads_explicit_env(monkeypatch, capsys) -> None:
    seen = {}
    _set_manifest(monkeypatch, build_manifest(), seen=seen)
    monkeypatch.setattr(
        "yoke_cli.operating_layer_drift.compare_installed_layer",
        lambda *args, **kwargs: None,
    )

    rc = yoke_operations_cli.main(["--env", "stage", "zz", "top"])

    assert rc == 2
    assert seen == {"explicit_env": "stage", "force_refresh": True}
    assert "unknown subcommand" in capsys.readouterr().err


def test_help_appends_server_only_drift_section(monkeypatch, capsys) -> None:
    _set_manifest(monkeypatch)

    rc = yoke_operations_cli.main(["--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Active env manifest:" in out
    assert "Active-env-only subcommands" in out
    assert "yoke zz top [source-dev/admin] -> zz.top.run" in out
    assert "Server usage: yoke zz top --afterburner" in out
    assert "public installer" not in out.lower()


def test_help_renders_without_manifest(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "yoke_cli.manifest.active_env_manifest",
        lambda **kwargs: None,
    )

    rc = yoke_operations_cli.main(["--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Active env manifest:" not in out
