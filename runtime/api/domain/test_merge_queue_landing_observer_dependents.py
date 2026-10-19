"""A landing the observer reads tells the blocker's dependents, once.

The blocker's own session may be gone when its pull request merges, so the
observer is the only writer that sees the merge in time. Its notice and the
one a later close-out sends share each edge's key, so the dependent hears
about the merge exactly once whichever writer gets there first.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from runtime.api.domain.merge_queue_observer_test_helpers import (
    GITHUB_MERGED_AT,
    MERGE_COMMIT,
    merged,
    unreadable,
)
from runtime.api.domain.test_dependency_satisfied_notice import (
    BLOCKER,
    DEPENDENT,
    _edge,
    _key,
    _parked_dependent,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    PROJECT_YOKE,
    _bodies,
    _project,
    _recipients,
)
from runtime.api.domain.test_session_message_support import NOW
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import item_landings_ops
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.project_identity import render_item_ref


def _unclosed_landing(conn: Any) -> None:
    """A blocker with its pull request open and no session holding it."""
    _project(conn)
    for item_id in (BLOCKER, DEPENDENT):
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="implementing",
        )
    conn.execute("UPDATE items SET merge_queue_pr_number='42' WHERE id=%s", (BLOCKER,))
    conn.commit()
    _edge(conn, BLOCKER, "integration", "fact:merged")
    _parked_dependent(conn)


def _close_out(conn: Any, monkeypatch: Any) -> Any:
    @contextmanager
    def connected():
        yield conn

    monkeypatch.setattr(item_landings_ops, "_connect_rw", connected)
    return item_landings_ops.handle_record_item_landing(
        FunctionCallRequest(
            function="item_landings.record",
            actor=ActorContext(session_id="closer"),
            target=TargetRef(kind="item", item_id=BLOCKER),
            payload={
                "merge_sha": MERGE_COMMIT,
                "candidate_sha": "cd" * 20,
                "pr_number": "42",
                "target_branch": "main",
                "route": "merge_queue",
                "landed_at": GITHUB_MERGED_AT,
            },
        )
    )


def test_an_observed_landing_tells_the_dependent_and_close_out_does_not_repeat(
    test_db: Any, monkeypatch: Any
) -> None:
    _unclosed_landing(test_db)

    observed = observe_pending_landings(
        test_db,
        [PROJECT_YOKE],
        now=NOW,
        read_state=merged,
        read_membership=unreadable,
        read_checks=unreadable,
    )

    assert observed["landed"] == 1
    assert "notice_errors" not in observed
    key = _key(test_db, "integration")
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    blocker_ref = render_item_ref(test_db, BLOCKER)
    assert body.startswith(f"{blocker_ref} merged; your integration gate fact:merged")

    recorded = _close_out(test_db, monkeypatch)

    assert recorded.primary_success, recorded.error
    assert recorded.result_payload["appended"] is True
    assert _bodies(test_db, key) == [body]


def test_a_repeated_observation_does_not_repeat_the_dependent_notice(
    test_db: Any,
) -> None:
    _unclosed_landing(test_db)

    for _ in range(2):
        observe_pending_landings(
            test_db,
            [PROJECT_YOKE],
            now=NOW,
            read_state=merged,
            read_membership=unreadable,
            read_checks=unreadable,
            cadence_seconds=0,
        )

    assert len(_bodies(test_db, _key(test_db, "integration"))) == 1
