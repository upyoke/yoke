"""The execute recipe creation prints names a real connection, not a blank."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import deployment_run_create
from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX, ENV_OVERRIDE


@pytest.fixture
def active_env(monkeypatch):
    def _set(value):
        if value is None:
            monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        else:
            monkeypatch.setenv(ENV_OVERRIDE, value)

    return _set


def test_an_https_connection_names_its_owner_only_sibling(active_env):
    # Creation dispatches over the product connection; execute needs the
    # owner-only one on the same control plane.
    active_env("prod")
    assert deployment_run_create._execute_authority() == f"prod{DB_ADMIN_ENV_SUFFIX}"


def test_an_owner_only_connection_names_itself_rather_than_doubling(active_env):
    active_env(f"prod{DB_ADMIN_ENV_SUFFIX}")
    assert deployment_run_create._execute_authority() == f"prod{DB_ADMIN_ENV_SUFFIX}"


def test_a_stage_control_plane_names_stage_not_production(active_env):
    active_env("stage")
    assert deployment_run_create._execute_authority() == f"stage{DB_ADMIN_ENV_SUFFIX}"


def test_surrounding_whitespace_does_not_produce_a_broken_env_name(active_env):
    active_env("  prod  ")
    assert deployment_run_create._execute_authority() == f"prod{DB_ADMIN_ENV_SUFFIX}"


def test_no_active_env_yields_empty_so_the_caller_keeps_the_placeholder(active_env):
    # Printing a confidently wrong recipe is worse than printing the
    # placeholder, because the operator stops checking once it looks resolved.
    active_env(None)
    assert deployment_run_create._execute_authority() == ""


def test_a_blank_active_env_is_treated_as_absent(active_env):
    active_env("   ")
    assert deployment_run_create._execute_authority() == ""


def test_a_bare_suffix_does_not_produce_a_dangling_env_name(active_env):
    active_env(DB_ADMIN_ENV_SUFFIX)
    assert deployment_run_create._execute_authority() == ""
