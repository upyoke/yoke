"""Migration admin entrypoints activate their explicit DB environment first."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from psycopg import conninfo

from runtime.api.tools import preflight_fleet_migrations as preflight
from runtime.api.tools import report_yoke_tenant_migration_state as reporter
from runtime.api.tools import yoke_migration_fleet
from runtime.api.tools.test_adopt_migration_content_identity import (
    _argv,
    _artifact,
    _legacy_connection,
    _mock_github_attestations,
)
from yoke_core.domain import connected_env_readiness as readiness
from yoke_core.domain import local_universe, migration_fleet_preflight
from yoke_core.tools import adopt_migration_content_identity as adopter
from yoke_core.tools import yoke_migration_fleet as fleet_selector


SELECTED_DSN = "host=selected.example user=admin dbname=postgres"


def _authority(environment: str) -> SimpleNamespace:
    return SimpleNamespace(environment=environment, dsn=SELECTED_DSN)


def _machine_config(release_env: str = "prod") -> dict[str, Any]:
    return {
        "connections": {
            release_env: {"transport": "https"},
            f"{release_env}-db-admin": {
                "transport": "local-postgres",
                "prod": True,
            },
            "stage": {"transport": "https"},
            "stage-db-admin": {"transport": "local-postgres", "prod": False},
        }
    }


def test_reporter_activates_before_fleet_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def activate(environment: str) -> SimpleNamespace:
        events.append(f"activate:{environment}")
        return _authority(environment)

    def discover(dsn_for: Any) -> list[str]:
        events.append("discover")
        assert conninfo.conninfo_to_dict(dsn_for("yoke_platform"))["host"] == (
            "selected.example"
        )
        return ["yoke_alpha"]

    monkeypatch.setattr(readiness, "activate_selected_postgres", activate)
    monkeypatch.setattr(fleet_selector, "tenant_databases", discover)
    monkeypatch.setattr(reporter, "_report_database", lambda *_args: True)

    assert reporter.main(["stage"]) == 0
    assert events == ["activate:stage", "discover"]


def test_adopter_activates_before_direct_database_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    _mock_github_attestations(monkeypatch)
    events: list[str] = []

    def activate(environment: str) -> SimpleNamespace:
        events.append(f"activate:{environment}")
        return _authority(environment)

    def connect(_database: str, *, authority_dsn: str):
        events.append("connect")
        assert authority_dsn == SELECTED_DSN
        return _legacy_connection()

    monkeypatch.setattr(readiness, "activate_selected_postgres", activate)
    monkeypatch.setattr(adopter, "_connect_database", connect)

    assert adopter.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 0
    assert events == ["activate:stage-db-admin", "connect"]


def test_preflight_keeps_receipt_on_preexisting_control_plane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    receipts: list[str] = []

    def activate(environment: str) -> SimpleNamespace:
        events.append(f"activate:{environment}")
        return _authority(environment)

    def rehearse(dsn_for: Any, **_kwargs: Any) -> list[SimpleNamespace]:
        events.append("rehearse")
        assert conninfo.conninfo_to_dict(dsn_for("yoke_alpha"))["host"] == (
            "selected.example"
        )
        return [SimpleNamespace(passed=True, line="yoke_alpha: PASS")]

    monkeypatch.setenv("YOKE_ENV", "release")
    monkeypatch.setattr(
        preflight.machine_config,
        "load_config",
        lambda: _machine_config("release"),
    )
    monkeypatch.setattr(readiness, "activate_selected_postgres", activate)
    monkeypatch.setattr(
        local_universe, "ensure_engine_binaries", lambda _emit: tmp_path
    )
    monkeypatch.setattr(
        local_universe,
        "cluster_spec",
        lambda **_kwargs: SimpleNamespace(sock_dir=tmp_path / "socket"),
    )
    monkeypatch.setattr(
        yoke_migration_fleet,
        "rehearsal_plan",
        lambda: SimpleNamespace(history=("0001_existing",)),
    )
    monkeypatch.setattr(migration_fleet_preflight, "rehearse_fleet", rehearse)
    monkeypatch.setattr(
        preflight,
        "_record_receipt",
        lambda **kwargs: (receipts.append(kwargs["receipt_env"]), "")[1],
    )

    assert (
        preflight.main(
            ["prod-db-admin", "yoke_alpha", "--record-receipt", "--product-sha", "abc"]
        )
        == 0
    )
    assert events == ["activate:prod-db-admin", "rehearse"]
    assert receipts == ["release"]


def test_preflight_resolves_an_environment_name_to_the_admin_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    def activate(environment: str) -> SimpleNamespace:
        events.append(f"activate:{environment}")
        return _authority(environment)

    def rehearse(dsn_for: Any, **_kwargs: Any) -> list[SimpleNamespace]:
        events.append("rehearse")
        return [SimpleNamespace(passed=True, line="yoke_alpha: PASS")]

    monkeypatch.setenv("YOKE_ENV", "release")
    monkeypatch.setattr(
        preflight.machine_config,
        "load_config",
        lambda: _machine_config("release"),
    )
    monkeypatch.setattr(readiness, "activate_selected_postgres", activate)
    monkeypatch.setattr(
        local_universe, "ensure_engine_binaries", lambda _emit: tmp_path
    )
    monkeypatch.setattr(
        local_universe,
        "cluster_spec",
        lambda **_kwargs: SimpleNamespace(sock_dir=tmp_path / "socket"),
    )
    monkeypatch.setattr(
        yoke_migration_fleet,
        "rehearsal_plan",
        lambda: SimpleNamespace(history=("0001_existing",)),
    )
    monkeypatch.setattr(migration_fleet_preflight, "rehearse_fleet", rehearse)
    monkeypatch.setattr(preflight, "_record_receipt", lambda **_kwargs: "")

    assert preflight.main(["stage", "yoke_alpha"]) == 0
    assert events == ["activate:stage-db-admin", "rehearse"]


def test_preflight_refuses_receipt_on_test_control_plane(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        preflight.machine_config,
        "load_config",
        lambda: _machine_config("release"),
    )

    assert (
        preflight.main(["stage-db-admin", "--record-receipt", "--receipt-env", "stage"])
        == 2
    )

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- stage-db-admin" in refusal
    assert "--receipt-env release" in refusal


def test_preflight_help_teaches_both_receipt_coverage_shapes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert preflight.main(["--help"]) == 0

    help_text = capsys.readouterr().out
    assert (
        "<admin-connection-for-one-env> --record-receipt --receipt-env <control-plane>"
    ) in help_text
    assert (
        "<admin-connection-for-another-env> --record-receipt "
        "--receipt-env <control-plane>"
    ) in help_text
    assert "The positional names the fleet to rehearse" in help_text
    assert "--receipt-env`` names the" in help_text
    assert "control plane that records the receipt" in help_text
    assert "one environment's receipt never satisfies another" in help_text
    assert "Receipts always write to the release-gate control plane" in help_text
    assert "yoke watch preflight -- stage --record-receipt" in help_text
    assert "Ordinary pre-release rehearsal uses the source tree" in help_text
    assert "--engine-wheel`` pins an already-built artifact" in help_text
