"""Terminal status transitions release resources atomically."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.workflow_version_test_helpers import (
    publish_issue_completion_stage,
)
from yoke_core.domain import (
    backlog,
    backlog_update_effects,
    backlog_update_op,
    item_status_transitions,
)
from runtime.api.domain._path_claims_test_helpers import (
    local_human,
    seed_target,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.path_claims import get_claim, register
from yoke_core.domain.work_claim_targets import (
    make_epic_task_target,
    make_item_target,
)


def test_terminal_cleanup_failure_rolls_back_status_lane_and_evidence(
    test_db,
    monkeypatch,
) -> None:
    """The terminal status and every DB closeout effect commit together."""
    _isolate_status_effects(monkeypatch)
    item_status_transitions.ensure_schema(test_db)
    item_id = 970
    insert_item(test_db, id=item_id, workflow_id="issue", status="release")
    record_item_worktree(
        test_db,
        item_id=item_id,
        branch="atomic-terminal-closeout",
        path=None,
        lane_role="implementation",
    )
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat, actor_id) "
        "VALUES ('terminal-rollback', 'codex', 'openai', 'gpt', '/tmp', 1, "
        "%s, %s, 1)",
        (now, now),
    )
    item_scope = make_item_target(item_id).scope_json()
    work_claim_id = test_db.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES "
        "('terminal-rollback', 'item', %s, 'exclusive', %s, %s) "
        "RETURNING id",
        (item_scope, now, now),
    ).fetchone()[0]
    from yoke_core.domain.ephemeral_env import cmd_create, cmd_update

    env_id = int(
        cmd_create(
            test_db,
            "yoke",
            "atomic-terminal-closeout",
            item=f"YOK-{item_id}",
        )
    )
    cmd_update(test_db, env_id, "status", "running")
    test_db.commit()
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )

    def fail_claim_cleanup(*_args, **_kwargs):
        raise RuntimeError("terminal cleanup interrupted")

    monkeypatch.setattr(
        backlog_update_effects,
        "_clean_terminal_path_claims",
        fail_claim_cleanup,
    )
    with pytest.raises(RuntimeError, match="terminal cleanup interrupted"):
        backlog.execute_update(
            item_id=item_id,
            field="status",
            value="done",
            done_nonce_verified=True,
            force=True,
            qa_bypass=True,
            no_github=True,
            rebuild_board=False,
        )

    item = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    lane = test_db.execute(
        "SELECT state FROM item_worktrees "
        "WHERE item_id=%s AND branch='atomic-terminal-closeout'",
        (item_id,),
    ).fetchone()
    transition_count = test_db.execute(
        "SELECT COUNT(*) FROM item_status_transitions "
        "WHERE item_id=%s AND to_status='done'",
        (item_id,),
    ).fetchone()[0]
    work_claim = test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s",
        (int(work_claim_id),),
    ).fetchone()
    environment = test_db.execute(
        "SELECT status FROM ephemeral_environments WHERE id=%s",
        (env_id,),
    ).fetchone()
    assert (str(item[0]), str(lane[0]), int(transition_count)) == (
        "release",
        "active",
        0,
    )
    assert work_claim[0] is None
    assert str(environment[0]) == "running"


def test_terminal_transition_releases_parent_and_task_work_claims(
    test_db,
    monkeypatch,
) -> None:
    """Parent and generated-task claims close in the status transaction."""
    _isolate_status_effects(monkeypatch)
    item_id = 972
    insert_item(test_db, id=item_id, workflow_id="issue", status="release")
    now = iso8601_now()
    for session_id in ("terminal-parent", "terminal-task"):
        test_db.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat, actor_id) "
            "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, 1)",
            (session_id, now, now),
        )
        test_db.execute(
            "UPDATE harness_sessions SET current_item_id=%s, "
            "current_item_set_at=%s WHERE session_id=%s",
            (item_id, now, session_id),
        )
    item_scope = make_item_target(item_id).scope_json()
    task_scope = make_epic_task_target(item_id, 1).scope_json()
    test_db.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES "
        "('terminal-parent', 'item', %s, 'exclusive', %s, %s)",
        (item_scope, now, now),
    )
    test_db.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES "
        "('terminal-task', 'epic_task', %s, 'exclusive', %s, %s)",
        (task_scope, now, now),
    )
    actor_id = local_human(test_db)
    target_id = seed_target(
        test_db,
        path_string="src/terminal_done.py",
    )
    path_claim_id = register(
        test_db,
        actor_id=actor_id,
        integration_target="main",
        target_ids=[target_id],
        item_id=item_id,
    )
    test_db.commit()
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )

    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="done",
        done_nonce_verified=True,
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    rows = test_db.execute(
        "SELECT target_kind, released_at, release_reason, "
        "release_reason_intent FROM work_claims "
        "WHERE scope IN (%s, %s) ORDER BY id",
        (item_scope, task_scope),
    ).fetchall()
    assert [str(row[0]) for row in rows] == ["item", "epic_task"]
    assert all(row[1] is not None for row in rows)
    assert {str(row[2]) for row in rows} == {"completed"}
    assert {str(row[3]) for row in rows} == {"item-terminal:done"}
    focuses = test_db.execute(
        "SELECT current_item_id FROM harness_sessions "
        "WHERE session_id IN ('terminal-parent', 'terminal-task') "
        "ORDER BY session_id",
    ).fetchall()
    assert [row[0] for row in focuses] == [None, None]
    assert get_claim(test_db, path_claim_id)["state"] == "released"


def test_custom_terminal_stops_non_yoke_item_environment(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    publish_issue_completion_stage(test_db, stage_id="archived")
    item_id = 975
    insert_item(
        test_db,
        id=item_id,
        workflow_id="issue",
        project="externalwebapp",
        status="done",
    )
    from yoke_core.domain.ephemeral_env import cmd_create, cmd_get_by_id

    env_id = int(
        cmd_create(
            test_db,
            "externalwebapp",
            "custom-prefix-terminal",
            item=str(item_id),
        )
    )
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )

    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="archived",
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    assert cmd_get_by_id(test_db, env_id, "status") == "stopped"


def test_pinned_custom_terminal_releases_resources_without_done_hardcoding(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    publish_issue_completion_stage(test_db, stage_id="archived")
    item_id = 974
    insert_item(test_db, id=item_id, workflow_id="issue", status="done")
    record_item_worktree(
        test_db,
        item_id=item_id,
        branch="custom-terminal",
        path=None,
        lane_role="implementation",
    )
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat, actor_id) "
        "VALUES ('custom-terminal', 'codex', 'openai', 'gpt', '/tmp', 1, "
        "%s, %s, 1)",
        (now, now),
    )
    item_scope = make_item_target(item_id).scope_json()
    test_db.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES "
        "('custom-terminal', 'item', %s, 'exclusive', %s, %s)",
        (item_scope, now, now),
    )
    actor_id = local_human(test_db)
    target_id = seed_target(
        test_db,
        path_string="src/custom_terminal.py",
    )
    path_claim_id = register(
        test_db,
        actor_id=actor_id,
        integration_target="main",
        target_ids=[target_id],
        item_id=item_id,
    )
    test_db.commit()
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )

    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="archived",
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    lane_state = test_db.execute(
        "SELECT state FROM item_worktrees WHERE item_id=%s",
        (item_id,),
    ).fetchone()[0]
    work_claim = test_db.execute(
        "SELECT released_at, release_reason_intent FROM work_claims "
        "WHERE target_kind='item' AND scope=%s",
        (item_scope,),
    ).fetchone()
    assert str(status) == "archived"
    assert str(lane_state) == "released"
    assert work_claim[0] is not None
    assert str(work_claim[1]) == "item-terminal:archived"
    assert get_claim(test_db, path_claim_id)["state"] == "released"
