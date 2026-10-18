"""Doctor diagnoses local credentials and actors independently of active authority."""

from pathlib import Path
import json

import pytest
from yoke_contracts.machine_config.runtime import write_config

from yoke_cli.config import machine_config, writer
from yoke_core.engines import doctor_hc_connections as checks
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def rows():
    rec = RecordCollector()
    checks.hc_connections(None, DoctorArgs(), rec)
    return rec.results


def test_missing_credential_file_names_local_repair_and_preserves_other_rows(home):
    writer.set_connection(
        "local", transport="local-postgres", dsn="host=/sock dbname=yoke"
    )
    Path(
        machine_config.load_config()["connections"]["local"]["credential_source"][
            "path"
        ]
    ).unlink()
    rec = RecordCollector()
    rec.record("prior", "Prior", "PASS", "previous check")
    checks.hc_connections(None, DoctorArgs(), rec)
    result = rec.results[-1]
    assert result.result == "FAIL"
    assert "CONNECTION_CREDENTIAL_FILE_MISSING" in result.detail
    assert "yoke init --local" in result.detail
    assert len(rec.results) == 2


def test_missing_https_token_has_its_own_recovery(home):
    writer.set_connection(
        "team", transport="https", api_url="https://api.example", token="t" * 40
    )
    Path(
        machine_config.load_config()["connections"]["team"]["credential_source"]["path"]
    ).unlink()
    assert "yoke --env team setup" in rows()[0].detail


@pytest.mark.parametrize("foreign_universe", [True, False])
def test_doctor_proves_actor_against_its_own_universe(home, test_db, foreign_universe):
    from yoke_core.domain import db_backend
    from yoke_core.domain.org_schema import seed_default_org
    from yoke_core.domain.universe_identity import universe_fingerprint

    payload = machine_config.load_config()
    payload["schema_version"] = 1
    write_config(machine_config.config_path(), payload)
    seed_default_org(test_db)
    test_db.commit()
    writer.set_connection(
        "local", transport="local-postgres", dsn=db_backend.resolve_pg_dsn()
    )
    payload = machine_config.load_config()
    actor_id = int(
        test_db.execute("SELECT id FROM actors WHERE kind='human' LIMIT 1").fetchone()[
            0
        ]
    )
    payload["connections"]["local"]["operating_actor"] = {
        "actor_id": actor_id if foreign_universe else 999999,
        "universe": "foreign@2020"
        if foreign_universe
        else universe_fingerprint(test_db),
    }
    write_config(machine_config.config_path(), payload)
    before = machine_config.config_path().read_bytes()
    result = rows()[0]
    assert result.result == "FAIL"
    assert "CONNECTION_OPERATING_ACTOR_INVALID" in result.detail
    assert (
        "SESSION_ACTOR_UNIVERSE_MISMATCH"
        if foreign_universe
        else "SESSION_ACTOR_UNBOUND"
    ) in result.detail
    assert "yoke init --local" in result.detail
    assert machine_config.config_path().read_bytes() == before


def test_doctor_cli_diagnoses_missing_active_secret_before_dispatch(
    home, capsys, monkeypatch
):
    from yoke_cli.commands.adapters import doctor

    writer.set_connection(
        "local", transport="local-postgres", dsn="host=/sock dbname=yoke"
    )
    Path(
        machine_config.load_config()["connections"]["local"]["credential_source"][
            "path"
        ]
    ).unlink()
    monkeypatch.setattr(
        doctor,
        "_dispatch_in_process",
        lambda **kw: pytest.fail("broken connection must not dispatch"),
    )
    assert doctor.doctor_run(["--quick", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "doctor_active_connection_unavailable"
    assert result["result"]["fail_count"] == 1


def test_healthy_check_records_pass_in_shared_collector(home):
    writer.set_connection(
        "local", transport="local-postgres", dsn="host=/sock dbname=yoke"
    )
    rec = RecordCollector()
    rec.record("prior", "Prior", "PASS", "previous check")
    checks.hc_connections(None, DoctorArgs(), rec)
    assert len(rec.results) == 2
    assert rec.results[-1].result == "PASS"


def test_doctor_respects_explicit_connection_override(home, monkeypatch):
    writer.set_connection(
        "local", transport="local-postgres", dsn="host=/sock dbname=yoke"
    )
    Path(
        machine_config.load_config()["connections"]["local"]["credential_source"][
            "path"
        ]
    ).unlink()
    writer.set_connection(
        "team", transport="https", api_url="https://api.example", token="t" * 40
    )
    writer.set_active_env("team")
    monkeypatch.setenv("YOKE_ENV", "local")
    assert (
        checks.active_connection_failure().error.code
        == "doctor_active_connection_unavailable"
    )
    monkeypatch.setenv("YOKE_ENV", "team")
    assert checks.active_connection_failure() is None


def test_unreachable_actor_is_unverified_and_credentials_stay_redacted(
    home, monkeypatch
):
    writer.set_connection(
        "local",
        transport="local-postgres",
        dsn="host=/sock password=private-password dbname=yoke",
    )
    payload = machine_config.load_config()
    payload["connections"]["local"]["operating_actor"] = {
        "actor_id": 1,
        "universe": "example@2020",
    }
    write_config(machine_config.config_path(), payload)

    def refused(*args, **kwargs):
        raise RuntimeError("private-password")

    monkeypatch.setattr(checks.db_backend, "connect_psycopg", refused)
    result = rows()[0]
    assert result.result == "WARN"
    assert "CONNECTION_ACTOR_UNVERIFIED" in result.detail
    assert "private-password" not in result.detail
