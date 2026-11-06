# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    seed_member_qa_case,
)

from yoke_core.domain.decision_related_evidence import related_screenshot_evidence

from yoke_core.domain.decision_request_contract import LIFECYCLE_TRANSITION_APPROVAL

from yoke_core.domain.decision_request_resolution import resolve_decision_request

from yoke_core.domain.decision_request_rows import request_row

from yoke_core.domain.decision_request_subject_context import (
    workflow_default_approval_source,
)

from yoke_core.domain.decision_requests import create_decision_request

from yoke_core.domain.lifecycle_approval_context import (
    build_lifecycle_subject_context,
    load_lifecycle_item,
)

MEMBER = 9861

EARLIER_RUN = "run-20260901-861"


def _seed_earlier_release(conn: Any) -> int:
    requirement = seed_member_qa_case(conn, run_id=EARLIER_RUN, member_item_id=MEMBER)
    conn.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE item_id=%s",
        (MEMBER,),
    )
    return requirement


def _pending_done_approval(conn: Any) -> int:
    actor = int(
        conn.execute(
            "INSERT INTO actors (kind, created_at) "
            "VALUES ('human', '2026-09-28T00:00:00Z') RETURNING id"
        ).fetchone()[0]
    )
    conn.execute("UPDATE items SET status='release' WHERE id=%s", (MEMBER,))
    item = load_lifecycle_item(conn, MEMBER)
    source = workflow_default_approval_source("done")
    # Raised before any capture existed, as a preexisting request would be.
    context = build_lifecycle_subject_context(conn, item, "done", source)
    request, _ = create_decision_request(
        conn,
        kind=LIFECYCLE_TRANSITION_APPROVAL,
        subject_type="item_transition",
        subject_key=f"{MEMBER}:done",
        project_id=int(item["project_id"]),
        named_actor_ids=(actor,),
        subject_context=context,
    )
    return int(request["id"])
