from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers, harness_machine_state
from yoke_core.domain.handlers import harness_machine_report


class _Connection:
    def close(self) -> None:
        pass


def test_machine_report_echoes_current_pack_prerequisite_readiness(monkeypatch) -> None:
    rows = [
        {
            "pack": "pulumi-foundation",
            "tool": "pulumi",
            "status": "missing",
            "code": "pack-prerequisite-missing",
            "detail": "pulumi is not on PATH",
            "install_recipe": "brew install pulumi/tap/pulumi",
        }
    ]
    monkeypatch.setattr(db_helpers, "connect", _Connection)
    monkeypatch.setattr(
        harness_machine_state,
        "upsert_harness_machine_reports",
        lambda conn, *, project_id, reports: reports,
    )
    request = FunctionCallRequest(
        function="harness.machine_report.upsert",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={"project_id": 7, "reports": [], "pack_prerequisites": rows},
    )

    outcome = harness_machine_report.handle_harness_machine_report_upsert(request)

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "project_id": 7,
        "reports": [],
        "pack_prerequisites": rows,
    }
