"""Deployment-destination routing for ``yoke onboard`` without the TUI.

Non-interactive parity lane: ``--local`` / ``--connect URL`` / the
destination environment override route to the same three destinations the
wizard's picker offers; the local lane drives the same universe-birth
machinery as ``yoke init --local``; rerunning onboarding ADDS connections
instead of switching them; and the chosen destination persists through the
apply-report snapshot so a resumed run restores it. The embedded-Postgres
engine is stubbed at ``local_universe_setup``'s engine seam; machine-config
writes are real and land under a scratch ``YOKE_MACHINE_HOME``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import local_universe_setup
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_resume
from yoke_cli.config import onboard_apply_snapshot
from yoke_cli.config import onboard_destinations
from yoke_cli.config import writer
from yoke_contracts.machine_config.schema import DEFAULT_TRANSPORT

FAKE_DSN = "postgresql://yoke@/yoke?host=/fake/local-universe/sock"
LOCAL = local_universe_setup.LOCAL_ENV


class _FakeEngine:
    """Stands in for the embedded-Postgres engine behind the birth seam."""

    def birth(self, *, org_name=None, emit=lambda _line: None):
        emit("fake engine: universe ready")
        return {
            "dsn": FAKE_DSN,
            "born": True,
            "cluster": {"root": "/fake/local-universe", "running": True},
            "org": {"name": org_name or "Local Org", "slug": "local-org"},
        }


@pytest.fixture()
def fake_engine(monkeypatch):
    monkeypatch.setattr(local_universe_setup, "_engine", lambda: _FakeEngine())


@pytest.fixture()
def scratch_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv(onboard_destinations.DESTINATION_OVERRIDE, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return home


def _config_payload(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


# ── pure destination resolution ──────────────────────────────────────────


def test_resolve_choice_flag_and_override_routing() -> None:
    resolve = onboard_destinations.resolve_choice
    assert resolve(local_flag=True) == (
        onboard_destinations.DESTINATION_LOCAL, None,
    )
    assert resolve(connect_url="https://api.mycompany.com") == (
        onboard_destinations.DESTINATION_SERVER, "https://api.mycompany.com",
    )
    # An explicit --connect at a hosted endpoint IS the hosted destination.
    assert resolve(connect_url="https://api.upyoke.com") == (
        onboard_destinations.DESTINATION_HOSTED, "https://api.upyoke.com",
    )
    assert resolve(override_value="local") == (
        onboard_destinations.DESTINATION_LOCAL, None,
    )
    assert resolve(override_value="https://yoke.example.test") == (
        onboard_destinations.DESTINATION_SERVER, "https://yoke.example.test",
    )
    assert resolve(resumed="hosted") == (
        onboard_destinations.DESTINATION_HOSTED, None,
    )
    assert resolve() == (None, None)
    # Flags outrank the override; the override outranks the resumed value.
    assert resolve(local_flag=True, override_value="hosted") == (
        onboard_destinations.DESTINATION_LOCAL, None,
    )
    assert resolve(override_value="hosted", resumed="local") == (
        onboard_destinations.DESTINATION_HOSTED, None,
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
            env_name="prod", api_url="https://api.test",
            destination="bogus", token="actor-token",
            mode="quick", apply=False, check_identity=False,
        )


# ── flag surface ──────────────────────────────────────────────────────────


def test_local_and_connect_flags_are_mutually_exclusive(
    scratch_home: Path, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "onboard", "--local", "--connect", "https://x.test",
        "--non-interactive", "--json",
    ])

    assert rc == 2
    assert "not allowed with" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [
    ["--api-url", "https://api.test"],
    ["--env", "stage"],
    ["actor-token"],
])
def test_local_flag_rejects_sign_in_inputs(
    scratch_home: Path, capsys, extra: list[str]
) -> None:
    rc = yoke_operations_cli.main(
        ["onboard", "--local", "--non-interactive", "--json", *extra]
    )

    assert rc == 2
    assert "--local" in capsys.readouterr().err


def test_connect_flag_conflicting_api_url_is_rejected(
    scratch_home: Path, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "onboard", "--connect", "https://a.test", "--api-url", "https://b.test",
        "--non-interactive", "--env", "prod", "--json", "tok",
    ])

    assert rc == 2
    assert "--connect URL and --api-url disagree" in capsys.readouterr().err


def test_destination_override_invalid_value_errors(
    scratch_home: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv(onboard_destinations.DESTINATION_OVERRIDE, "sideways")

    rc = yoke_operations_cli.main(["onboard", "--non-interactive", "--json"])

    assert rc == 2
    assert onboard_destinations.DESTINATION_OVERRIDE in capsys.readouterr().err


# ── local destination: dry run and apply ─────────────────────────────────


def test_destination_override_env_var_routes_local(
    scratch_home: Path, fake_engine, monkeypatch, capsys
) -> None:
    monkeypatch.setenv(
        onboard_destinations.DESTINATION_OVERRIDE,
        onboard_destinations.DESTINATION_LOCAL,
    )

    rc = yoke_operations_cli.main(["onboard", "--non-interactive", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["destination"] == onboard_destinations.DESTINATION_LOCAL
    assert "local-universe-init" in [
        step["action"] for step in payload["plan"]["steps"]
    ]


def _normalized_local_connection(home: Path) -> dict:
    payload = _config_payload(home)
    connection = dict(payload["connections"][LOCAL])
    source = dict(connection.get("credential_source") or {})
    dsn_path = source.pop("path", "")
    connection["credential_source"] = source
    connection["dsn_value"] = Path(dsn_path).read_text(encoding="utf-8").strip()
    connection["active_env"] = payload.get("active_env")
    return connection


def test_local_apply_lands_config_like_yoke_init_local(
    tmp_path: Path, fake_engine, monkeypatch, capsys
) -> None:
    init_home = tmp_path / "init-home"
    onboard_home = tmp_path / "onboard-home"

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(init_home))
    assert yoke_operations_cli.main(["init", "--local", "--json"]) == 0
    capsys.readouterr()

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(onboard_home))
    rc = yoke_operations_cli.main([
        "onboard", "--local", "--non-interactive", "--yes", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["applied"] is True
    assert payload["identity"]["status"] == "local-universe"
    assert payload["local_universe"]["connection_written"] is True
    assert (
        _normalized_local_connection(init_home)
        == _normalized_local_connection(onboard_home)
    )
    assert _normalized_local_connection(onboard_home)["dsn_value"] == FAKE_DSN
    assert _config_payload(onboard_home)["active_env"] == LOCAL


def test_local_apply_adds_connection_beside_existing_hosted(
    scratch_home: Path, fake_engine, capsys
) -> None:
    config_path = scratch_home / "config.json"
    writer.set_connection(
        "prod", transport="https", api_url="https://api.upyoke.com",
        token="a-plausible-hosted-actor-token-value", path=config_path,
    )
    writer.set_active_env("prod", path=config_path)

    rc = yoke_operations_cli.main([
        "onboard", "--local", "--non-interactive", "--yes", "--json",
    ])

    assert rc == 0
    capsys.readouterr()
    payload = _config_payload(scratch_home)
    assert set(payload["connections"]) == {"prod", LOCAL}
    assert payload["connections"]["prod"]["transport"] == "https"
    # Completing the local flow makes local active without touching the
    # hosted connection.
    assert payload["active_env"] == LOCAL


def test_hosted_apply_keeps_existing_local_connection(
    scratch_home: Path, fake_engine, capsys
) -> None:
    local_universe_setup.run_local_init(
        config_path=str(scratch_home / "config.json"),
    )

    rc = yoke_operations_cli.main([
        "onboard", "a-plausible-hosted-actor-token-value",
        "--non-interactive", "--quick", "--env", "prod",
        "--api-url", "https://api.upyoke.com",
        "--yes", "--skip-identity-check", "--json",
    ])

    assert rc == 0
    capsys.readouterr()
    payload = _config_payload(scratch_home)
    assert set(payload["connections"]) == {"prod", LOCAL}
    assert payload["connections"][LOCAL]["transport"] == DEFAULT_TRANSPORT
    # active_env follows the newly completed flow.
    assert payload["active_env"] == "prod"


# ── snapshot persistence + resume restore ────────────────────────────────


def test_legacy_api_url_lane_stamps_server_destination(
    scratch_home: Path, capsys
) -> None:
    """``--api-url`` alone (no ``--local``/``--connect``) derives the
    destination the URL implies, so the report and the resume snapshot
    preset the team-server lane — a resumed run must not silently flip a
    self-hosted onboarding to the hosted default."""
    rc = yoke_operations_cli.main([
        "onboard", "a-plausible-team-server-actor-token-value",
        "--non-interactive", "--quick", "--env", "prod",
        "--api-url", "https://yoke.example.test",
        "--yes", "--skip-identity-check", "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["destination"] == onboard_destinations.DESTINATION_SERVER
    run_report = json.loads(
        Path(payload["apply_report"]["path"]).read_text(encoding="utf-8")
    )
    snapshot = run_report["input_snapshot"]
    assert snapshot["destination"] == onboard_destinations.DESTINATION_SERVER
    assert snapshot["api_url"] == "https://yoke.example.test"


def test_snapshot_records_destination_and_resume_restores_it() -> None:
    snapshot = onboard_apply_snapshot.build({
        "config_path": "/home/u/.yoke/config.json",
        "env_name": LOCAL,
        "api_url": "",
        "destination": onboard_destinations.DESTINATION_LOCAL,
        "mode": "quick",
        "check_identity": False,
    })
    assert snapshot["destination"] == onboard_destinations.DESTINATION_LOCAL

    parsed = SimpleNamespace(
        config_path=None, env_name=None, api_url=None, destination=None,
        token=None, token_file=None,
    )
    onboard_apply_resume.apply_defaults(parsed, snapshot)
    assert parsed.destination == onboard_destinations.DESTINATION_LOCAL
    assert parsed.env_name == LOCAL
