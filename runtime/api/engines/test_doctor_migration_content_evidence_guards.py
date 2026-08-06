"""Doctor refusal when Yoke adoption evidence loses an immutability guard."""

from dataclasses import dataclass
import sqlite3

from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    ensure_yoke_migration_ledger,
)
from yoke_core.engines import (
    doctor_context,
    doctor_project_migration_state as resolution,
)
from yoke_core.engines.doctor_hc_project_migration_ledger import (
    hc_project_migration_ledger_contract,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@dataclass
class _State:
    authority_conn: sqlite3.Connection
    project: str = "yoke"
    model_name: str = "primary"
    history: tuple = ()
    ledger: object = YOKE_LEDGER_CONTRACT
    running_version: str | None = None
    artifact_version_env_var: str | None = None

    def close(self) -> None:
        pass


def test_dropped_evidence_guard_fails_yoke_ledger_contract(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    trigger = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
        "AND tbl_name = 'migration_content_adoptions' ORDER BY name LIMIT 1"
    ).fetchone()[0]
    conn.execute(f'DROP TRIGGER "{trigger}"')
    state = _State(conn)
    monkeypatch.setattr(
        resolution,
        "resolve_project_migration_state",
        lambda *_: state,
    )
    monkeypatch.setattr(doctor_context, "self_project_names", lambda *_: ("yoke",))
    recorder = RecordCollector()

    hc_project_migration_ledger_contract(
        conn,
        DoctorArgs(project="yoke"),
        recorder,
    )

    assert len(recorder.results) == 1
    assert recorder.results[0].result == "FAIL"
    assert "append-only guards are missing" in recorder.results[0].detail
