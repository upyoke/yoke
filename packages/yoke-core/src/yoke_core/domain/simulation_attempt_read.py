"""Verify a simulation's own durable attempt, without selecting a newer run."""

import json

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.epic_parsing import _placeholder
from yoke_core.domain.simulation_report_headers import SimulationReceipt


class SimulationReadbackError(RuntimeError):
    code = "simulation_readback_failed"

    def __init__(self, receipt: SimulationReceipt):
        self.requirement_id = receipt.requirement_id
        self.run_id = receipt.run_id
        super().__init__(
            f"{self.code}: could not verify requirement {receipt.requirement_id}, run {receipt.run_id}. "
            f"Re-read with yoke workflow-item epic-task simulation-get --epic {receipt.public_ref} "
            f"--phase {receipt.phase}; do not repeat the write."
        )


def verify_simulation_attempt(conn, item_id: int, receipt: SimulationReceipt) -> None:
    try:
        p = _placeholder(conn)
        row = query_one(
            conn,
            f"""SELECT qr.qa_requirement_id, qreq.item_id, qreq.qa_kind,
                       qreq.success_policy, qr.qa_kind AS run_kind, qr.verdict, qr.raw_result
                FROM qa_runs qr JOIN qa_requirements qreq ON qreq.id = qr.qa_requirement_id
                WHERE qr.id = {p}""",
            (receipt.run_id,),
        )
        valid = row is not None and (
            int(row["qa_requirement_id"]) == receipt.requirement_id
            and int(row["item_id"]) == item_id
            and row["qa_kind"] == row["run_kind"] == "simulation"
            and json.loads(row["success_policy"])["phase"] == receipt.phase
            and json.loads(row["raw_result"])["phase"] == receipt.phase
            and row["verdict"]
            == {"CLEAN": "pass", "GAPS FOUND": "fail"}[receipt.verdict]
        )
        if not valid:
            raise SimulationReadbackError(receipt)
    except SimulationReadbackError:
        raise
    except Exception as exc:
        raise SimulationReadbackError(receipt) from exc
