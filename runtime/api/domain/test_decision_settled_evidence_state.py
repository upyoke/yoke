"""A resolved approval's frozen "missing screenshot" warning is re-checked.

A request resolved before screenshot warnings were limited to screenshot
checks froze ``missing`` for a subject whose checks are command checks. The
read gives the state those checks support instead; a subject that does have
a screenshot check keeps the warning, and the frozen screenshots never change.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.test_decision_member_release_evidence import (
    _pending_done_approval,
    _seed_earlier_release,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_rows import request_row


def _resolved_with_frozen_missing(conn: Any) -> int:
    request_id = _pending_done_approval(conn)
    actor = request_row(conn, request_id)["named_actor_ids"][0]
    resolve_decision_request(conn, request_id, actor_id=actor, action="approve")
    stored = json.loads(
        conn.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s", (request_id,)
        ).fetchone()[0]
    )
    # As a request resolved under the earlier rule froze it.
    stored["evidence"] = {**stored["evidence"], "state": "missing", "screenshots": []}
    conn.execute(
        "UPDATE decision_requests SET subject_context=%s WHERE id=%s",
        (json.dumps(stored), request_id),
    )
    conn.commit()
    return request_id


def test_command_checks_drop_a_frozen_missing_warning(test_db) -> None:
    _seed_earlier_release(test_db)
    request_id = _resolved_with_frozen_missing(test_db)

    evidence = request_row(test_db, request_id)["subject_context"]["evidence"]

    assert evidence["state"] == "not_expected"
    assert evidence["screenshots"] == []


def test_a_screenshot_check_keeps_the_frozen_warning(test_db) -> None:
    requirement = _seed_earlier_release(test_db)
    test_db.execute(
        "UPDATE qa_requirements SET method_id='browser-inspection' WHERE id=%s",
        (requirement,),
    )
    request_id = _resolved_with_frozen_missing(test_db)

    evidence = request_row(test_db, request_id)["subject_context"]["evidence"]

    assert evidence["state"] == "missing"
