"""Tests for the install-topology helper."""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.migration_install_topology import (
    is_single_authoritative_install,
    project_model_is_single_install,
)
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


def test_single_install_with_path_location():
    model = {
        "authoritative_db": {
            "kind": "sqlite_file",
            "location": {"path": "data/yoke.db"},
        },
    }
    assert is_single_authoritative_install(model) is True


def test_no_authoritative_db_returns_false():
    assert is_single_authoritative_install({}) is False


def test_empty_location_returns_false():
    model = {"authoritative_db": {"kind": "sqlite_file", "location": {}}}
    assert is_single_authoritative_install(model) is False


def test_explicit_multi_install_list_returns_false():
    model = {
        "authoritative_db": {
            "installs": [
                {"path": "data/install_a.db"},
                {"path": "data/install_b.db"},
            ],
        },
    }
    assert is_single_authoritative_install(model) is False


def test_single_entry_installs_list_treated_as_single_install():
    """A future schema may put one install in the ``installs`` list — still
    single-install topology."""
    model = {
        "authoritative_db": {
            "installs": [{"path": "data/yoke.db"}],
            "location": {"path": "data/yoke.db"},
        },
    }
    assert is_single_authoritative_install(model) is True


def test_list_shaped_location_with_two_entries_returns_false():
    model = {
        "authoritative_db": {
            "location": [
                {"path": "data/a.db"},
                {"path": "data/b.db"},
            ],
        },
    }
    assert is_single_authoritative_install(model) is False


class TestProjectModelIsSingleInstallRegression:
    """End-to-end regression for the validation-surface contract.

    Pins that ``project_model_is_single_install`` resolves
    ``project_capabilities`` from the canonical Yoke control-plane DB
    regardless of which connection the caller hands in.
    """

    def test_resolves_through_canonical_when_conn_is_validation_surface(
        self, apply_env,
    ) -> None:
        validation_conn = db_backend.connect_psycopg(apply_env["validation_dsn"])
        try:
            with pytest.raises(db_backend.operational_error_types(validation_conn)):
                validation_conn.execute(
                    "SELECT 1 FROM project_capabilities LIMIT 1"
                )
            # The failed probe poisons the Postgres transaction; recover the
            # connection before handing it to the resolver under test.
            validation_conn.rollback()
            assert project_model_is_single_install(
                validation_conn, "yoke", "primary"
            ) is True
        finally:
            validation_conn.close()

    def test_resolves_through_canonical_when_conn_is_canonical(
        self, apply_env,
    ) -> None:
        canonical_conn = _conn(apply_env["control_db"])
        try:
            assert project_model_is_single_install(
                canonical_conn, "yoke", "primary"
            ) is True
        finally:
            canonical_conn.close()
