"""A disposable database must not be created on a cluster nobody here owns.

The failure covered is not hypothetical: a session holding the prod admin
connection for preflight evidence ran a suite in the same shell, the suite
inherited that connection as its cluster, and two ``yoke_test_run*``
databases were left on production when it was interrupted. The next release's
fleet rehearsal converged them and refused on a ledger belonging to a run that
had already exited.

These tests exercise the guard and the naming factory every creator routes
through, because a refusal that fires before any cluster is contacted is the
property that matters.
"""

from __future__ import annotations

import pytest

from yoke_contracts import schema_authority
from yoke_core.domain import administered_postgres
from yoke_core.domain import pg_test_db_namespace as namespace
from yoke_core.domain import scratch_database_authority as authority
from yoke_contracts.control_plane_locality import PG_DSN_ENV, PG_DSN_FILE_ENV

ADMIN_ENV = "prod-db-admin"
LOCAL_ENV = "local"


def _select(monkeypatch: pytest.MonkeyPatch, env: str, connection: dict) -> None:
    """Make one connection the selected one for both readers of the config."""
    runtime = schema_authority.machine_config_runtime
    assert runtime is administered_postgres.machine_config_runtime
    monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: env)
    monkeypatch.setattr(runtime, "active_connection", lambda **_kwargs: connection)


@pytest.fixture(autouse=True)
def _no_named_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test with nothing but the connection naming a cluster."""
    monkeypatch.delenv(PG_DSN_ENV, raising=False)
    monkeypatch.delenv(PG_DSN_FILE_ENV, raising=False)


@pytest.fixture
def administering_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the prod-flagged Postgres connection the leak came through."""
    _select(
        monkeypatch,
        ADMIN_ENV,
        {"transport": "local-postgres", "prod": True},
    )


@pytest.fixture
def local_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _select(
        monkeypatch,
        LOCAL_ENV,
        {"transport": "local-postgres", "prod": False},
    )


class TestWhereTheDatabaseWouldLand:
    def test_administered_cluster_is_named(
        self, administering_connection: None
    ) -> None:
        assert authority.administering_scratch_cluster() == ADMIN_ENV

    def test_local_connection_creates_on_its_own_cluster(
        self, local_connection: None
    ) -> None:
        assert authority.administering_scratch_cluster() == ""

    def test_relayed_prod_connection_hands_out_no_cluster(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An https connection is prod-flagged and still cannot receive a
        # database: it relays. Refusing here would stop every ordinary run of
        # a machine whose selected connection is the hosted product plane.
        _select(monkeypatch, "prod", {"transport": "https", "prod": True})

        assert authority.administering_scratch_cluster() == ""

    def test_an_explicit_dsn_names_its_own_cluster(
        self, administering_connection: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # How the sanctioned runners keep working: the suite is pointed at the
        # local test cluster even while an administering connection is
        # selected, so the connection is not where the database lands.
        monkeypatch.setenv(PG_DSN_ENV, "host=/tmp/pgsock dbname=postgres")

        assert authority.administering_scratch_cluster() == ""

    def test_unreadable_machine_config_does_not_manufacture_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(**_kwargs: object) -> object:
            raise RuntimeError("machine config is broken for an unrelated reason")

        monkeypatch.setattr(
            schema_authority.machine_config_runtime, "active_env", explode
        )
        assert authority.administering_scratch_cluster() == ""


class TestRefusal:
    def test_creation_is_refused_with_the_connection_and_the_way_out(
        self, administering_connection: None
    ) -> None:
        with pytest.raises(authority.ScratchDatabaseRefused) as refused:
            authority.refuse_scratch_database_on_administered_cluster(
                "yoke_test_run1x2_ambient"
            )

        message = str(refused.value)
        assert "yoke_test_run1x2_ambient" in message
        assert ADMIN_ENV in message
        assert "pg_testcluster start" in message
        assert "drop_leftover_test_databases" in message
        assert "owned_scratch_cluster()" in message

    def test_refusal_is_not_catchable_as_an_ordinary_exception(
        self, administering_connection: None
    ) -> None:
        # The provisioning this guards sits under conftest imports and pytest
        # fixtures, which swallow Exception subclasses into one more red line.
        assert not issubclass(authority.ScratchDatabaseRefused, Exception)

    def test_local_connection_creates_without_ceremony(
        self, local_connection: None
    ) -> None:
        authority.refuse_scratch_database_on_administered_cluster("yoke_test_run1x2_a")

    def test_a_caller_owning_its_cluster_declares_and_proceeds(
        self, administering_connection: None
    ) -> None:
        assert not authority.owned_scratch_cluster_declared()
        with authority.owned_scratch_cluster():
            assert authority.owned_scratch_cluster_declared()
            authority.refuse_scratch_database_on_administered_cluster(
                "yoke_test_run1x2_owned"
            )
        assert not authority.owned_scratch_cluster_declared()


class TestEveryCreatorInheritsIt:
    def test_the_naming_factory_refuses_before_a_name_exists(
        self, administering_connection: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every creator has to come through database_name to get a name any
        # ownership check downstream will accept, so guarding it is what makes
        # a creator added later inherit the refusal without knowing about it.
        monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=7))

        with pytest.raises(authority.ScratchDatabaseRefused):
            namespace.database_name("ambient_gw0")

    def test_the_naming_factory_is_untouched_on_an_owned_cluster(
        self, local_connection: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(namespace.RUN_TAG_ENV, namespace.mint_run_tag(pid=7))

        assert namespace.database_name("ambient_gw0").endswith("_ambient_gw0")
