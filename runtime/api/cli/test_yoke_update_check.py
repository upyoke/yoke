"""Tests for `yoke update --check`: which side is behind the channel latest."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands.adapters import self_update as command
from yoke_cli.config import self_update, update_check
from yoke_cli.self_host import release_target
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL, KIND_SOURCE_CHECKOUT

LATEST = "0.2.0.202610170000"
OLDER = "0.2.0.202610100000"
HOSTED_URL = "https://app.upyoke.com/api/orgs/acme"
TEAM_URL = "https://yoke.example.com"
COMMIT = "e2ec8be23286fbc918a6375dc2717c3d612dc87c"
WHEELS = [{"filename": "yoke_cli-0.2.0-py3-none-any.whl", "sha256": "a" * 64}]


def _binding(kind: str, version: str) -> dict:
    return {
        "kind": kind,
        "checkout_root": "/work/yoke" if kind == KIND_SOURCE_CHECKOUT else None,
        "module_origin": "/wherever/yoke_cli/__init__.py",
        "version": version,
        "source_commit": COMMIT if kind == KIND_PACKAGED_WHEEL else "",
    }


@pytest.fixture
def install(monkeypatch):
    """Patch the installed CLI, channel latest and active connection."""

    def configure(*, cli=LATEST, transport="https", api_url=HOSTED_URL, server=LATEST):
        monkeypatch.setattr(
            update_check.install_binding,
            "detect",
            lambda: _binding(KIND_PACKAGED_WHEEL, cli),
        )
        monkeypatch.setattr(
            self_update,
            "resolve_target",
            lambda **_k: release_target.ReleaseTarget(
                version=LATEST,
                source_commit="3" * 40,
                image="",
                base_url="https://distribution.example",
                channel="stable",
                installer_url="https://distribution.example/dist/install.py",
            ),
        )
        monkeypatch.setattr(
            update_check.machine_config,
            "active_connection",
            lambda: {"env": "prod", "transport": transport, "api_url": api_url},
        )
        monkeypatch.setattr(
            update_check.manifest,
            "fetch_env_manifest",
            lambda _env: {"server_engine_version": server} if server else None,
        )
        monkeypatch.setattr(
            update_check.manifest, "diagnose_env_manifest_fetch", lambda _env: "401"
        )
        monkeypatch.setattr(update_check, "installed_engine_version", lambda: cli)
        monkeypatch.setattr(
            update_check.release_build,
            "verify_installed",
            lambda **kwargs: (
                WHEELS
                if kwargs
                == {
                    "version": cli,
                    "source_commit": COMMIT,
                    "base_url": "https://distribution.example",
                }
                else pytest.fail(f"unexpected build proof request {kwargs}")
            ),
        )

    return configure


def test_current_hosted_install_is_behind_nothing(install):
    install()
    report = update_check.run_check()
    assert (report["source_commit"], report["wheels"]) == (COMMIT, WHEELS)
    assert report["behind"] == "none"
    assert report["destination"] == "hosted"
    assert report["server_engine_version"] == LATEST
    assert report["next_step"] == ""


def test_older_cli_is_behind_and_told_to_run_update(install):
    install(cli=OLDER)
    report = update_check.run_check()
    assert (report["behind"], report["cli_version"]) == ("cli", OLDER)
    assert "Run `yoke update`" in report["next_step"]


def test_hosted_server_behind_waits_for_the_hosted_release(install):
    install(server=OLDER)
    report = update_check.run_check()
    assert report["behind"] == "server"
    assert "hosted release" in report["next_step"]


def test_team_server_behind_names_the_server_admin(install):
    install(api_url=TEAM_URL, server=OLDER)
    report = update_check.run_check()
    assert (report["behind"], report["destination"]) == ("server", "server")
    assert "server admin" in report["next_step"]


def test_local_universe_reads_its_own_engine(install):
    install(cli=OLDER, transport="local-postgres", api_url="")
    report = update_check.run_check()
    assert report["destination"] == "local"
    assert report["server_engine_version"] == OLDER
    assert report["behind"] == "cli"
    assert "local server together" in report["next_step"]


def test_unreadable_server_version_refuses_with_its_reason(install):
    install(server="")
    with pytest.raises(self_update.SelfUpdateError) as raised:
        update_check.run_check()
    assert "server_version_unavailable" in str(raised.value)
    assert "401" in str(raised.value)


def test_source_checkout_refuses(monkeypatch):
    monkeypatch.setattr(
        update_check.install_binding,
        "detect",
        lambda: _binding(KIND_SOURCE_CHECKOUT, ""),
    )
    with pytest.raises(self_update.SelfUpdateError, match="source checkout"):
        update_check.run_check()


def test_check_json_never_installs(install, monkeypatch, capsys):
    install(cli=OLDER)
    monkeypatch.setattr(
        self_update, "run_update", lambda **_k: pytest.fail("--check must not install")
    )
    assert command.update(["--check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["behind"] == "cli"
    assert payload["latest_version"] == LATEST
    assert (payload["source_commit"], payload["wheels"]) == (COMMIT, WHEELS)


def test_check_refuses_an_exact_version(install):
    install()
    with pytest.raises(SystemExit):
        command.update(["--check", "--version", LATEST])


def test_build_mismatch_refuses_the_check(install, monkeypatch, capsys):
    install()

    def mismatch(**_kwargs):
        raise update_check.release_build.ReleaseBuildError(
            "installed_build_mismatch: reinstall"
        )

    monkeypatch.setattr(update_check.release_build, "verify_installed", mismatch)
    assert command.update(["--check", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "error": "installed_build_mismatch: reinstall"}


def test_check_text_names_the_commit_and_wheel_hashes(install, capsys):
    install()
    assert command.update(["--check"]) == 0
    out = capsys.readouterr().out
    assert f"built from {COMMIT}" in out
    assert f"{WHEELS[0]['filename']} sha256 {'a' * 64}" in out


def test_missing_active_env_refuses_with_env_use_recovery(install, monkeypatch, capsys):
    install()

    def unconfigured():
        raise update_check.machine_config.contract.MachineConfigContractError(
            "active env is not configured; run `yoke env use <env>` or pass --env"
        )

    monkeypatch.setattr(update_check.machine_config, "active_connection", unconfigured)
    assert command.update(["--check"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("yoke update --check: active_connection_unavailable:")
    assert "`yoke env use <env>`" in out
    assert "Traceback" not in out
