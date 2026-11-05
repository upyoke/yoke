# ruff: noqa: F811
"""The /yoke idea draft claim keeps other workers off an item mid-authoring.

Exercised through the live ``claim-work`` / ``release-work-claim`` CLI
surface. The title-only guard lives in ``test_item_spec_required``.
"""

from __future__ import annotations

import json
import os
import subprocess

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import db_backend
from runtime.api.service_client_sessions_helpers_test_support import (
    _pre_register_session,
)
from runtime.api.service_client_test_support import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)
from yoke_core.domain.work_claim_targets import make_item_target


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run_client(args, db_path=None):
    """Worktree-aware service-client subprocess wrapper for race tests.

    Pinning ``cwd`` and ``PYTHONPATH`` to this worktree forces nested
    subprocesses to resolve packages and ``runtime`` helpers from the
    same checkout that hosts this test.
    """
    env = os.environ.copy()
    if db_path:
        env["YOKE_DB"] = db_path
    if "--session-id" in args:
        sid_index = list(args).index("--session-id") + 1
        if sid_index < len(args):
            env["YOKE_SESSION_ID"] = args[sid_index]
    return subprocess.run(
        _service_client_cmd(list(args)),
        capture_output=True,
        text=True,
        env=_with_source_pythonpath(env),
        cwd=_REPO_ROOT,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Layer 1 — claim-on-create blocks the live race window
# ---------------------------------------------------------------------------


def test_draft_claim_blocks_other_worker_assignment_until_release(session_test_db):
    from yoke_core.domain.scheduler import compute_schedule
    from yoke_core.domain.scheduler_types import is_assignable_claim_state

    db_path = session_test_db["db_path"]
    workspace = session_test_db["tmp_dir"]
    item_num = 10
    public_ref = f"YOK-{item_num}"
    _pre_register_session(db_path, "drafter", workspace=workspace)
    _pre_register_session(db_path, "worker", workspace=workspace)
    claim = _run_client(
        [
            "claim-work",
            "--session-id",
            "drafter",
            "--reason",
            "draft-in-progress",
            "--item",
            public_ref,
        ],
        db_path=db_path,
    )
    assert claim.returncode == 0, claim.stderr
    conn = connect_test_db(db_path)
    try:
        schedule = compute_schedule(
            conn, project_scope=["yoke"], session_id="worker", emit_events=False
        )
        held = next(step for step in schedule.ranked_steps if step.item_id == item_num)
        assert not is_assignable_claim_state(held.claim_state)
    finally:
        conn.close()
    release = _run_client(
        [
            "release-work-claim",
            "--session-id",
            "drafter",
            "--reason",
            "idea-complete",
            "--item",
            public_ref,
        ],
        db_path=db_path,
    )
    assert release.returncode == 0, release.stderr
    conn = connect_test_db(db_path)
    try:
        schedule = compute_schedule(
            conn, project_scope=["yoke"], session_id="worker", emit_events=False
        )
        available = next(
            step for step in schedule.ranked_steps if step.item_id == item_num
        )
        assert is_assignable_claim_state(available.claim_state)
    finally:
        conn.close()


def test_layer1_release_emits_idea_claim_held_event(session_test_db):
    """Happy-path release with idea-complete intent emits IdeaClaimHeld."""
    db_path = session_test_db["db_path"]
    drafter_id = "drafter-emit"
    item_num = 10
    public_ref = f"YOK-{item_num}"
    _pre_register_session(db_path, drafter_id)

    claim = _run_client(
        [
            "claim-work",
            "--session-id",
            drafter_id,
            "--reason",
            "draft-in-progress",
            "--item",
            public_ref,
        ],
        db_path=db_path,
    )
    assert claim.returncode == 0, claim.stderr

    release = _run_client(
        [
            "release-work-claim",
            "--session-id",
            drafter_id,
            "--reason",
            "idea-complete",
            "--item",
            public_ref,
        ],
        db_path=db_path,
    )
    assert release.returncode == 0, release.stderr

    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'IdeaClaimHeld' "
            f"AND session_id = {p} ORDER BY id DESC LIMIT 1",
            (drafter_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, "IdeaClaimHeld event was not emitted"
    envelope = json.loads(rows[0][0])
    context = envelope.get("context") or {}
    assert context.get("release_reason_intent") == "idea-complete"
    assert context.get("claim_reason_intent") == "draft-in-progress"
    assert context.get("duration_ms", -1) >= 0
    assert context.get("claim_id") is not None
    assert context.get("claimed_at")
    assert context.get("released_at")
    assert envelope.get("item_id") == str(item_num)


def test_layer1_dispatcher_release_canonicalizes_and_emits(
    session_test_db, monkeypatch
):
    """Dispatcher path mirrors the CLI path for ``idea-complete``.

    Pins three contracts the SKILL's ``claims.work.release`` call relies on:
    storage gets the canonical ``handed_off``; ``release_reason_intent``
    preserves the original ``idea-complete`` on ``WorkReleased``;
    ``IdeaClaimHeld`` fires because ``is_idea_release_intent`` keys on intent.
    """
    import uuid

    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import FunctionCallRequest

    db_path = session_test_db["db_path"]
    drafter_id = "drafter-dispatcher"
    monkeypatch.setenv("YOKE_DB", db_path)
    monkeypatch.setenv("YOKE_SESSION_ID", drafter_id)

    item_num = 10
    public_ref = f"YOK-{item_num}"
    _pre_register_session(db_path, drafter_id)

    claim = _run_client(
        [
            "claim-work",
            "--session-id",
            drafter_id,
            "--reason",
            "draft-in-progress",
            "--item",
            public_ref,
        ],
        db_path=db_path,
    )
    assert claim.returncode == 0, claim.stderr

    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        target = make_item_target(item_num)
        row = conn.execute(
            f"SELECT id FROM work_claims WHERE session_id = {p} "
            f"AND target_kind = {p} AND scope = {p} "
            "AND released_at IS NULL",
            (drafter_id, target.kind, target.scope_json()),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "draft claim row was not created"
    claim_id = int(row[0])

    resp = dispatch(
        FunctionCallRequest(
            function="claims.work.release",
            request_id=str(uuid.uuid4()),
            actor={"session_id": drafter_id},
            target={"kind": "claim", "claim_id": claim_id},
            payload={"claim_id": claim_id, "reason": "idea-complete"},
        )
    )
    assert resp.success, f"dispatcher release failed: {resp.error}"

    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        storage = conn.execute(
            f"SELECT release_reason FROM work_claims WHERE id = {p}",
            (claim_id,),
        ).fetchone()
        event_rows = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'IdeaClaimHeld' "
            f"AND session_id = {p} ORDER BY id DESC LIMIT 1",
            (drafter_id,),
        ).fetchall()
    finally:
        conn.close()

    assert storage is not None and storage[0] == "handed_off", (
        f"dispatcher must canonicalize 'idea-complete' to 'handed_off'"
        f" in storage; got {None if storage is None else storage[0]!r}"
    )
    assert len(event_rows) == 1, "IdeaClaimHeld must fire via dispatcher path"
    envelope = json.loads(event_rows[0][0])
    context = envelope.get("context") or {}
    assert context.get("release_reason_intent") == "idea-complete"
    assert context.get("claim_reason_intent") == "draft-in-progress"
    assert context.get("duration_ms", -1) >= 0
