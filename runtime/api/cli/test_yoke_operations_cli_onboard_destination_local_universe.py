"""Local-universe plan transitions for non-interactive onboarding."""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import onboard_destinations
from yoke_contracts.machine_config.schema import DEFAULT_TRANSPORT

from runtime.api.cli.test_yoke_operations_cli_onboard_destination import (
    LOCAL,
    _config_payload,
    fake_engine,  # noqa: F401
    scratch_home,  # noqa: F401
)


def _plan_step(payload: dict, action: str) -> dict:
    return next(step for step in payload["plan"]["steps"] if step["action"] == action)


def test_local_dry_run_plans_universe_init_without_sign_in_steps(
    scratch_home: Path, fake_engine, capsys
) -> None:
    rc = yoke_operations_cli.main([
        "onboard", "--local", "--non-interactive", "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["destination"] == onboard_destinations.DESTINATION_LOCAL
    actions = [step["action"] for step in payload["plan"]["steps"]]
    assert "local-universe-init" in actions
    assert _plan_step(payload, "local-universe-init")["target"] == "create"
    assert "set-https-api-url" not in actions
    assert "store-token-reference" not in actions
    assert payload["plan"]["active_env"] == LOCAL
    assert payload["plan"]["connection"]["transport"] == DEFAULT_TRANSPORT
    assert not (scratch_home / "config.json").exists()


def test_local_rerun_verifies_universe_and_keeps_active_env(
    scratch_home: Path, fake_engine, capsys
) -> None:
    payload: dict = {}
    for _ in range(2):
        assert yoke_operations_cli.main([
            "onboard", "--local", "--non-interactive", "--yes", "--json",
        ]) == 0
        payload = json.loads(capsys.readouterr().out)

    assert payload["applied"] is True
    assert _plan_step(payload, "local-universe-init")["target"] == "verify"
    config = _config_payload(scratch_home)
    assert config["active_env"] == LOCAL
    assert set(config["connections"]) == {LOCAL}
