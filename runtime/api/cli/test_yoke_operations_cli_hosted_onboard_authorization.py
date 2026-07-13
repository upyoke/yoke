"""Yoke Cloud onboarding authorization boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import local_universe_setup
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_destinations
from yoke_contracts.machine_config.schema import DEFAULT_TRANSPORT


LOCAL = local_universe_setup.LOCAL_ENV
FAKE_DSN = "postgresql://yoke@/yoke?host=/fake/local-universe/sock"


class _FakeEngine:
    def birth(self, *, org_name=None, emit=lambda _line: None):
        return {
            "dsn": FAKE_DSN,
            "born": True,
            "cluster": {"root": "/fake/local-universe", "running": True},
            "org": {"name": org_name or "Local Org", "slug": "local-org"},
        }


@pytest.fixture()
def scratch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv(onboard_destinations.DESTINATION_OVERRIDE, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return home


def test_public_onboarding_defaults_to_the_local_universe() -> None:
    assert (
        onboard_destinations.DEFAULT_DESTINATION
        == onboard_destinations.DESTINATION_LOCAL
    )


def test_resolve_choice_routes_flags_overrides_and_resumes() -> None:
    resolve = onboard_destinations.resolve_choice
    assert resolve(local_flag=True) == (onboard_destinations.DESTINATION_LOCAL, None)
    assert resolve(connect_url="https://api.mycompany.com") == (
        onboard_destinations.DESTINATION_SERVER,
        "https://api.mycompany.com",
    )
    assert resolve(connect_url="https://api.upyoke.com") == (
        onboard_destinations.DESTINATION_HOSTED,
        "https://api.upyoke.com",
    )
    assert resolve(override_value="local") == (
        onboard_destinations.DESTINATION_LOCAL,
        None,
    )
    assert resolve(override_value="https://yoke.example.test") == (
        onboard_destinations.DESTINATION_SERVER,
        "https://yoke.example.test",
    )
    assert resolve(resumed="hosted") == (
        onboard_destinations.DESTINATION_HOSTED,
        None,
    )
    assert resolve() == (None, None)
    assert resolve(local_flag=True, override_value="hosted") == (
        onboard_destinations.DESTINATION_LOCAL,
        None,
    )
    assert resolve(override_value="hosted", resumed="local") == (
        onboard_destinations.DESTINATION_HOSTED,
        None,
    )


def test_resolve_choice_rejects_unusable_override() -> None:
    with pytest.raises(ValueError):
        onboard_destinations.resolve_choice(override_value="bogus")
    with pytest.raises(ValueError):
        onboard_destinations.resolve_choice(override_value="server")


def test_build_report_rejects_unknown_destination(tmp_path: Path) -> None:
    with pytest.raises(onboard_config.OnboardError):
        onboard_config.build_report(
            config_path=str(tmp_path / "config.json"),
            env_name="prod",
            api_url="https://api.test",
            destination="bogus",
            token="actor-token",
            mode="quick",
            apply=False,
            check_identity=False,
        )


@pytest.mark.parametrize(
    "hosted_args",
    [
        ["manual-cloud-token"],
        ["--token-file", "/tmp/manual-cloud-token"],
        ["--token-stdin"],
    ],
)
def test_hosted_destination_rejects_every_manual_token_source(
    scratch_home: Path,
    capsys: pytest.CaptureFixture[str],
    hosted_args: list[str],
) -> None:
    rc = yoke_operations_cli.main(
        [
            "onboard",
            "--connect",
            "https://app.upyoke.com",
            "--non-interactive",
            "--json",
            *hosted_args,
        ]
    )

    assert rc == 2
    error = capsys.readouterr().err
    assert "Yoke Cloud uses browser approval" in error
    assert "remove TOKEN, --token-file, or --token-stdin" in error


def test_hosted_destination_rejects_noninteractive_fresh_connection(
    scratch_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = yoke_operations_cli.main(
        [
            "onboard",
            "--connect",
            "https://app.upyoke.com",
            "--non-interactive",
            "--json",
        ]
    )

    assert rc == 2
    assert "Yoke Cloud onboarding requires browser approval" in capsys.readouterr().err


def test_hosted_api_url_rejects_manual_token_without_touching_local_connection(
    scratch_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(local_universe_setup, "_engine", lambda: _FakeEngine())
    config = scratch_home / "config.json"
    local_universe_setup.run_local_init(config_path=str(config))

    rc = yoke_operations_cli.main(
        [
            "onboard",
            "a-plausible-hosted-actor-token-value",
            "--non-interactive",
            "--quick",
            "--env",
            "prod",
            "--api-url",
            "https://api.upyoke.com",
            "--yes",
            "--skip-identity-check",
            "--json",
        ]
    )

    assert rc == 2
    assert "Yoke Cloud uses browser approval" in capsys.readouterr().err
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert set(payload["connections"]) == {LOCAL}
    assert payload["connections"][LOCAL]["transport"] == DEFAULT_TRANSPORT
    assert payload["active_env"] == LOCAL


def test_resume_reuses_hosted_browser_approved_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    token_file = tmp_path / "browser-approved.token"
    token_file.write_text("browser-approved-credential", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    preview = {
        "operation": "onboard",
        "mode": "quick",
        "project_mode": "machine-only",
        "config_path": str(config),
        "plan": {"project": None, "steps": []},
    }
    writer = onboard_apply_report.ApplyReportWriter.start(
        preview,
        {
            "config_path": str(config),
            "env_name": "prod",
            "api_url": "https://api.upyoke.com",
            "destination": "hosted",
            "token_file": str(token_file),
            "token_source_kind": "file",
            "mode": "quick",
            "project_mode": "machine-only",
        },
    )
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard(
        [
            "--resume",
            run_id,
            "--yes",
            "--non-interactive",
            "--skip-identity-check",
        ]
    )

    assert rc == 0
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["connections"]["prod"]["api_url"] == "https://api.upyoke.com"
    managed_token = Path(payload["connections"]["prod"]["credential_source"]["path"])
    assert managed_token != token_file
    assert (
        managed_token.read_text(encoding="utf-8").strip()
        == token_file.read_text(encoding="utf-8").strip()
    )
