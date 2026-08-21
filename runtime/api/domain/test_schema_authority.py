"""A process that does not serve a database must not change its schema.

The failure being covered is not hypothetical: an ordinary command run from a
workstation against a prod-flagged connection applied the ordered history to a
production control plane, moving it ahead of every build reading it. The guard
therefore keys on the connection rather than on which command reached it, and
these tests exercise the kernels themselves — a refusal that fires before the
connection is touched at all is the property that matters.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_contracts import schema_authority
from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import migration_boot_apply, schema_init
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT

PROD_ENV = "prod-db-admin"
SERVED_ENV = "prod"


@pytest.fixture
def prod_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select a prod-flagged connection for the duration of one test."""
    monkeypatch.setattr(
        schema_authority.machine_config_runtime,
        "active_env",
        lambda **_kwargs: PROD_ENV,
    )
    monkeypatch.setattr(
        schema_authority.machine_config_runtime,
        "active_connection",
        lambda **_kwargs: {"transport": "local-postgres", "prod": True},
    )


@pytest.fixture
def local_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        schema_authority.machine_config_runtime,
        "active_env",
        lambda **_kwargs: "local",
    )
    monkeypatch.setattr(
        schema_authority.machine_config_runtime,
        "active_connection",
        lambda **_kwargs: {"transport": "local-postgres", "prod": False},
    )


class TestConnectionDecidesAuthority:
    def test_prod_flagged_connection_is_named(self, prod_connection: None) -> None:
        assert schema_authority.prod_flagged_connection() == PROD_ENV

    def test_local_connection_carries_no_refusal(
        self, local_connection: None
    ) -> None:
        assert schema_authority.prod_flagged_connection() == ""
        schema_authority.refuse_without_serving_build_authority("converging")

    def test_unreadable_machine_config_does_not_manufacture_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(**_kwargs: object) -> object:
            raise RuntimeError("machine config is broken for an unrelated reason")

        monkeypatch.setattr(
            schema_authority.machine_config_runtime, "active_env", explode
        )
        assert schema_authority.prod_flagged_connection() == ""

    def test_refusal_names_the_connection_and_the_way_out(
        self, prod_connection: None
    ) -> None:
        with pytest.raises(schema_authority.SchemaAuthorityRefused) as excinfo:
            schema_authority.refuse_without_serving_build_authority("converging")
        message = str(excinfo.value)
        assert PROD_ENV in message
        assert "serving_build_authority" in message

    def test_refusal_is_not_an_ordinary_exception(
        self, prod_connection: None
    ) -> None:
        # The migration and convergence paths are full of blanket
        # ``except Exception`` handlers that log and continue. A refusal any
        # of them could swallow would be swallowed exactly where the silence
        # was fatal.
        assert not issubclass(schema_authority.SchemaAuthorityRefused, Exception)
        swallowed = False
        try:
            schema_authority.refuse_without_serving_build_authority("converging")
        except Exception:  # noqa: BLE001 - the shape the refusal must survive
            swallowed = True
        except schema_authority.SchemaAuthorityRefused:
            pass
        assert not swallowed

    def test_a_process_that_serves_the_database_may_change_it(
        self, prod_connection: None
    ) -> None:
        with schema_authority.serving_build_authority():
            assert schema_authority.serving_build_authority_declared()
            schema_authority.refuse_without_serving_build_authority("converging")
        assert not schema_authority.serving_build_authority_declared()


class TestKernelsRefuseBeforeTouchingTheDatabase:
    """``conn`` is ``None`` on purpose: reaching it at all fails the test."""

    def test_converge_refuses(self, prod_connection: None) -> None:
        with pytest.raises(schema_authority.SchemaAuthorityRefused):
            schema_init.converge_core_schema(None)

    def test_apply_refuses(self, prod_connection: None) -> None:
        with pytest.raises(schema_authority.SchemaAuthorityRefused):
            migration_boot_apply.apply_pending(
                None,
                history=(),
                ledger=YOKE_LEDGER_CONTRACT,
                applied_by="test",
                running_version="",
                attribution={},
                model_name="",
            )

    def test_stamping_a_history_as_applied_refuses(
        self, prod_connection: None
    ) -> None:
        with pytest.raises(schema_authority.SchemaAuthorityRefused):
            migration_boot_apply.stamp_history(
                None, (), ledger=YOKE_LEDGER_CONTRACT, applied_by="test"
            )


class TestRehearsalRefusesProductionOutright:
    def test_prod_control_plane_is_refused_with_the_reason(
        self, prod_connection: None
    ) -> None:
        refusal = schema_authority.refuse_on_prod_control_plane("rehearsal")
        assert refusal is not None
        assert PROD_ENV in refusal
        assert "validation surface" in refusal

    def test_the_refusal_is_not_exemptible(self, prod_connection: None) -> None:
        # Rehearsal targets a disposable copy by definition, so no caller has
        # standing to declare authority over a production control plane.
        with schema_authority.serving_build_authority():
            assert schema_authority.refuse_on_prod_control_plane("rehearsal")

    def test_a_non_prod_connection_rehearses(self, local_connection: None) -> None:
        assert schema_authority.refuse_on_prod_control_plane("rehearsal") is None


def _select(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    connections: dict[str, dict[str, object]],
    active_env: str,
    override: str | None,
) -> None:
    """Point the contract at a machine config and select one env within it."""
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"active_env": active_env, "connections": connections})
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    if override is None:
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
    else:
        monkeypatch.setenv(ENV_OVERRIDE, override)


PAIRED_UNIVERSE: dict[str, dict[str, object]] = {
    SERVED_ENV: {"transport": "https"},
    PROD_ENV: {"transport": "local-postgres", "prod": True},
    "local": {"transport": "local-postgres", "prod": False},
}


class TestChildCommandsDoNotInheritAdministeringAuthority:
    """A command shelled out to holds no opinion about the parent's authority.

    The observed failure ran a project's own test suite from a boundary that
    had taken the administering connection for its control-plane work. Every
    schema the suite converged on a disposable database of its own was refused,
    because the guard reads the ambient selection rather than the target.
    """

    def test_administering_selection_is_swapped_for_the_served_sibling(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _select(
            monkeypatch, tmp_path,
            connections=PAIRED_UNIVERSE, active_env=SERVED_ENV, override=PROD_ENV,
        )
        assert schema_authority.prod_flagged_connection() == PROD_ENV

        env = schema_authority.environment_without_administering_selection()

        assert env[ENV_OVERRIDE] == SERVED_ENV

    def test_an_administering_default_is_swapped_rather_than_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Dropping the override would leave the child resolving the same
        # administering connection through the config's own default.
        _select(
            monkeypatch, tmp_path,
            connections=PAIRED_UNIVERSE, active_env=PROD_ENV, override=None,
        )

        env = schema_authority.environment_without_administering_selection()

        assert env[ENV_OVERRIDE] == SERVED_ENV

    def test_a_served_selection_passes_through_untouched(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _select(
            monkeypatch, tmp_path,
            connections=PAIRED_UNIVERSE, active_env=SERVED_ENV, override=SERVED_ENV,
        )

        assert (
            schema_authority.environment_without_administering_selection()
            == dict(os.environ)
        )

    def test_a_local_universe_passes_through_untouched(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _select(
            monkeypatch, tmp_path,
            connections=PAIRED_UNIVERSE, active_env="local", override="local",
        )

        assert (
            schema_authority.environment_without_administering_selection()
            == dict(os.environ)
        )

    def test_no_served_sibling_leaves_the_selection_alone(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Substituting some other universe's connection would send the child
        # to rows that are not its own — worse than the refusal it avoids.
        _select(
            monkeypatch, tmp_path,
            connections={
                "solo": {"transport": "local-postgres", "prod": True},
                "local": {"transport": "local-postgres", "prod": False},
            },
            active_env="solo",
            override="solo",
        )

        assert (
            schema_authority.environment_without_administering_selection()
            == dict(os.environ)
        )
