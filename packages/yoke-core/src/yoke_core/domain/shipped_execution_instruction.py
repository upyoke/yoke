"""Shipped execution instruction for a newly born universe.

The prose is the general execution rules a new install starts with.
A universe that already stores this exact prose is left unchanged.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_execution_instructions import (
    create_instruction,
    set_instruction_scope,
)

SHIPPED_WORKFLOW_IDS = ("blitz", "dash", "epic", "issue")

SHIPPED_EXECUTION_INSTRUCTION = "EXECUTION RULES (apply to this entire item):\n- Finish the whole agreed scope in this change, including every affected call site. Do not defer parts to follow-up work or leave remaining sites for later. If the work turns out larger than described, it is still this work.\n- Remove obsolete paths when you replace them. Do not add compatibility layers, fallbacks, aliases or shims, unless the project must keep existing users or callers working across versions; then make that support explicit and time-boxed.\n- Choose the simplest implementation that fully meets the requirement. No speculative abstraction, configuration, or indirection.\n- Grow in layers: get the smallest version working end to end first, then add each capability on top of something that already works. Never trade a working product for unfinished complexity.\n- Keep components modular with clearly separated concerns.\n- Prefer established, well-maintained libraries where they reduce complexity or improve reliability. Lean on dependencies already in the project before writing your own implementation; check their docs and types before assuming a capability is missing.\n- Make architectural decisions for the long term. Do not accept a stopgap meant to be replaced later.\n- Fail loudly and teach the fix. Wherever your change can refuse, time out, or crash, it must surface a named reason plus the recovery step, and record evidence where the affected person or agent will actually look. A path that reports success while the work silently failed is a defect; so is a raw traceback where a diagnosed refusal belongs.\n- A change is not done when the code works. Update the surface that owns the changed behavior. Teach it in other surfaces, at their own level of detail, only where that helps the reader there. In the same change, delete or rewrite any text the change makes wrong or redundant, so nothing teaches the old behavior and no surface grows without need.\n- Infrastructure is declared, never clicked. Anything your change stands up or alters outside the repository — cloud resources, buckets and their policies, CDNs, DNS records, queues, roles and permissions, scheduled jobs, dashboards, webhooks, third-party project or account settings — lands as infrastructure-as-code in the project's declared IaC surface, in the same change. Do not create it in a provider console or with an ad hoc CLI call and move on: an undeclared resource is invisible to every other environment, cannot be reviewed or rebuilt, and drifts silently. If you created something by hand while investigating, either import it into the IaC declaration or destroy it and let the declaration create it, and say which you did. Emergency live patches are followed immediately by the declaration catching up.\n- Logs and telemetry are disposable. Operational code may emit them but must never depend on their presence, retention or delivery. Store facts the system needs in its durable data store. Diagnostics may read telemetry; missing telemetry proves nothing."


class ShippedExecutionInstructionError(RuntimeError):
    """Birth cannot attach the shipped instruction to its workflows."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def seed_shipped_execution_instruction(conn: Any) -> int:
    """Insert the shipped instruction once, after builtin workflows exist.

    Returns the existing or new row id. Matching content is not rewritten,
    so a universe that already carries the prose keeps its scope. A missing
    builtin workflow refuses ``shipped_execution_instruction_workflows_missing``
    and names the workflows birth must converge first.
    """
    placeholder = _placeholder(conn)
    row = conn.execute(
        "SELECT id FROM workflow_execution_instructions WHERE content = " + placeholder,
        (SHIPPED_EXECUTION_INSTRUCTION,),
    ).fetchone()
    if row is not None:
        return int(row[0])

    marks = ", ".join(placeholder for _ in SHIPPED_WORKFLOW_IDS)
    present = {
        str(found[0])
        for found in conn.execute(
            f"SELECT id FROM workflows WHERE id IN ({marks})",
            SHIPPED_WORKFLOW_IDS,
        ).fetchall()
    }
    missing = [
        workflow_id
        for workflow_id in SHIPPED_WORKFLOW_IDS
        if workflow_id not in present
    ]
    if missing:
        raise ShippedExecutionInstructionError(
            "shipped_execution_instruction_workflows_missing",
            "Builtin workflows are not converged: "
            + ", ".join(missing)
            + ". Recovery: run schema init again after builtin workflow convergence.",
        )
    instruction_id = create_instruction(conn, content=SHIPPED_EXECUTION_INSTRUCTION)
    set_instruction_scope(
        conn,
        instruction_id,
        workflow_ids=list(SHIPPED_WORKFLOW_IDS),
        applies_to_all_workflows=False,
        applies_to_all_projects=True,
        project_ids=[],
    )
    conn.commit()
    return instruction_id
