"""Doctor exposes scratch databases stranded on administered clusters."""

from __future__ import annotations

from yoke_core.domain.administered_postgres import AdministeredPostgresTarget
from yoke_core.engines import doctor_hc_scratch_databases as check
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run(monkeypatch, targets, names_by_dsn=None):
    monkeypatch.setattr(
        check.administered_postgres,
        "configured_administered_targets",
        lambda: tuple(targets),
    )
    names_by_dsn = names_by_dsn or {}
    monkeypatch.setattr(
        check,
        "_scratch_database_names",
        lambda dsn: tuple(names_by_dsn.get(dsn, ())),
    )
    collector = RecordCollector()
    check.hc_administered_scratch_databases(None, DoctorArgs(), collector)
    assert len(collector.results) == 1
    return collector.results[0]


def _target(env="prod-db-admin", dsn="admin-dsn"):
    return AdministeredPostgresTarget(
        env=env,
        endpoint=(("loopback", "6547"),),
        dsn=dsn,
    )


def test_no_administered_cluster_is_not_applicable(monkeypatch) -> None:
    result = _run(monkeypatch, ())

    assert result.result == "N/A"
    assert "no prod-flagged local-Postgres" in result.detail


def test_clean_administered_cluster_passes(monkeypatch) -> None:
    result = _run(monkeypatch, (_target(),))

    assert result.result == "PASS"
    assert "0 yoke_test_run*" in result.detail


def test_leftovers_fail_with_review_and_manual_drop_recipes(monkeypatch) -> None:
    result = _run(
        monkeypatch,
        (_target(),),
        {"admin-dsn": ("yoke_test_run12xabc_ambient_main",)},
    )

    assert result.result == "FAIL"
    assert "yoke_test_run12xabc_ambient_main" in result.detail
    assert (
        "YOKE_ENV=prod-db-admin python3 -m "
        "runtime.api.tools.drop_leftover_test_databases --dry-run"
    ) in result.detail
    assert (
        "YOKE_ENV=prod-db-admin python3 -m "
        "runtime.api.tools.drop_leftover_test_databases`"
    ) in result.detail


def test_unavailable_credential_is_a_visible_warning(monkeypatch) -> None:
    target = AdministeredPostgresTarget(
        env="prod-db-admin",
        endpoint=(("loopback", "6547"),),
        dsn=None,
    )

    result = _run(monkeypatch, (target,))

    assert result.result == "WARN"
    assert "credential DSN is unavailable" in result.detail
    assert "yoke status" in result.detail


def test_connection_failure_names_recovery_without_rendering_the_dsn(
    monkeypatch,
) -> None:
    target = _target(dsn="password=secret host=127.0.0.1")
    monkeypatch.setattr(
        check.administered_postgres,
        "configured_administered_targets",
        lambda: (target,),
    )
    monkeypatch.setattr(
        check,
        "_scratch_database_names",
        lambda _dsn: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    collector = RecordCollector()

    check.hc_administered_scratch_databases(None, DoctorArgs(), collector)

    result = collector.results[0]
    assert result.result == "WARN"
    assert "RuntimeError" in result.detail
    assert "restore its tunnel or credential" in result.detail
    assert "secret" not in result.detail
