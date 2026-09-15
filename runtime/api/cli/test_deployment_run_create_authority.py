"""The execute recipe keeps the run's selected control-plane connection."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import deployment_run_create
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


@pytest.fixture
def active_env(monkeypatch):
    def _set(value):
        if value is None:
            monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        else:
            monkeypatch.setenv(ENV_OVERRIDE, value)

    return _set


def test_an_https_connection_names_itself(active_env):
    active_env("prod")
    assert deployment_run_create._execute_connection() == "prod"


def test_an_owner_only_connection_still_names_itself(active_env):
    active_env("prod-db-admin")
    assert deployment_run_create._execute_connection() == "prod-db-admin"


def test_a_stage_control_plane_names_stage(active_env):
    active_env("stage")
    assert deployment_run_create._execute_connection() == "stage"


def test_surrounding_whitespace_does_not_produce_a_broken_env_name(active_env):
    active_env("  prod  ")
    assert deployment_run_create._execute_connection() == "prod"


def test_no_active_env_yields_empty_so_the_caller_keeps_the_placeholder(active_env):
    # Printing a confidently wrong recipe is worse than printing the
    # placeholder, because the operator stops checking once it looks resolved.
    active_env(None)
    assert deployment_run_create._execute_connection() == ""


def test_a_blank_active_env_is_treated_as_absent(active_env):
    active_env("   ")
    assert deployment_run_create._execute_connection() == ""
