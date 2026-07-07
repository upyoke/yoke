"""Pairing test for the /yoke idea -> frontier race guard.

Covers the guard's three failure modes: live race, stale-heartbeat tail,
and happy-path regression. Layer 1 (claim-on-create) is
exercised through the live ``claim-work`` / ``release-work-claim`` CLI
surface; Layer 2 (frontier body-completeness skip) runs against the
in-memory frontier helpers.
"""

from __future__ import annotations

import json
import os
import subprocess

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import db_backend
from yoke_core.domain.frontier import (
    AdapterCategory,
    FrontierResult,
    compute_frontier,
)
from yoke_core.domain.idea_body_completeness import (
    INCOMPLETE_REASON,
    is_idea_body_incomplete,
)
from runtime.api.frontier_test_helpers import insert_item, make_test_db
from runtime.api.test_service_client_sessions_helpers import (  # noqa: F401
    _pre_register_session,
    session_offer_db,
)
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)
from runtime.api.test_constants import TEST_MODEL_ID


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


def _offer(session_id: str, *, db_path: str, workspace: str):
    return _run_client(
        [
            "session-offer",
            "--executor", "DARIUS",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", workspace,
            "--session-id", session_id,
            "--step", "1",
        ],
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Layer 1 — claim-on-create blocks the live race window
# ---------------------------------------------------------------------------


def test_layer1_draft_claim_blocks_concurrent_session_offer(session_offer_db):
    """A held draft claim keeps the item out of another session's offer."""
    db_path = session_offer_db["db_path"]
    workspace = session_offer_db["tmp_dir"]
    drafter_id = "drafter-session"
    poacher_id = "poacher-session"
    item_num = 10
    item_ref = f"YOK-{item_num}"

    _pre_register_session(db_path, drafter_id, workspace=workspace)
    _pre_register_session(db_path, poacher_id, workspace=workspace)

    # Drafter claims with the canonical draft intent.
    drafter = _run_client(
        [
            "claim-work",
            "--session-id", drafter_id,
            "--reason", "draft-in-progress",
            "--item", item_ref,
        ],
        db_path=db_path,
    )
    assert drafter.returncode == 0, drafter.stderr

    # Poacher offers for work while the draft claim is held. The claimed
    # item must not be selected or advertised as runnable.
    poacher = _offer(poacher_id, db_path=db_path, workspace=workspace)
    assert poacher.returncode == 0, poacher.stderr
    poacher_offer = json.loads(poacher.stdout)
    context = poacher_offer.get("context") or {}
    assert context.get("selected_item") != item_ref
    assert item_ref not in context.get("runnable_items", [])

    # Drafter releases with the canonical idea-complete intent.
    release = _run_client(
        [
            "release-work-claim",
            "--session-id", drafter_id,
            "--reason", "idea-complete",
            "--item", item_ref,
        ],
        db_path=db_path,
    )
    assert release.returncode == 0, release.stderr

    # After release, the same offer path can select the item.
    poacher_post = _offer(poacher_id, db_path=db_path, workspace=workspace)
    assert poacher_post.returncode == 0, poacher_post.stderr
    post_offer = json.loads(poacher_post.stdout)
    assert post_offer["action"] == "charge"
    assert post_offer["context"]["selected_item"] == item_ref


def test_layer1_release_emits_idea_claim_held_event(session_offer_db):
    """Happy-path release with idea-complete intent emits IdeaClaimHeld."""
    db_path = session_offer_db["db_path"]
    drafter_id = "drafter-emit"
    item_num = 10
    item_ref = f"YOK-{item_num}"
    _pre_register_session(db_path, drafter_id)

    claim = _run_client(
        [
            "claim-work",
            "--session-id", drafter_id,
            "--reason", "draft-in-progress",
            "--item", item_ref,
        ],
        db_path=db_path,
    )
    assert claim.returncode == 0, claim.stderr

    release = _run_client(
        [
            "release-work-claim",
            "--session-id", drafter_id,
            "--reason", "idea-complete",
            "--item", item_ref,
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
    session_offer_db, monkeypatch
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

    db_path = session_offer_db["db_path"]
    drafter_id = "drafter-dispatcher"
    monkeypatch.setenv("YOKE_DB", db_path)
    monkeypatch.setenv("YOKE_SESSION_ID", drafter_id)

    item_num = 11
    item_ref = f"YOK-{item_num}"
    _pre_register_session(db_path, drafter_id)

    claim = _run_client(
        ["claim-work", "--session-id", drafter_id,
         "--reason", "draft-in-progress", "--item", item_ref],
        db_path=db_path,
    )
    assert claim.returncode == 0, claim.stderr

    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT id FROM work_claims WHERE session_id = {p} "
            f"AND item_id = {p} AND released_at IS NULL",
            (drafter_id, item_num),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "draft claim row was not created"
    claim_id = int(row[0])

    resp = dispatch(FunctionCallRequest(
        function="claims.work.release",
        request_id=str(uuid.uuid4()),
        actor={"session_id": drafter_id},
        target={"kind": "claim", "claim_id": claim_id},
        payload={"claim_id": claim_id, "reason": "idea-complete"},
    ))
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


# ---------------------------------------------------------------------------
# Layer 2 — frontier body-completeness skip catches the stale-heartbeat tail
# ---------------------------------------------------------------------------


def test_layer2_title_only_idea_is_classified_blocked():
    """Title-only idea bodies land in blocked, not runnable."""
    conn = make_test_db()
    stale_id = 50
    real_id = 51
    insert_item(
        conn,
        stale_id,
        title="Stale draft",
        status="idea",
        spec="# Stale draft",
    )
    insert_item(conn, real_id, title="Real idea", status="idea")  # default helper spec
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    assert isinstance(result, FrontierResult)
    runnable_ids = [fi.item_id for fi in result.runnable]
    blocked_ids = [fi.item_id for fi in result.blocked]
    stale_ref = f"YOK-{stale_id}"
    assert stale_ref in blocked_ids
    assert f"YOK-{real_id}" in runnable_ids
    blocked_50 = next(fi for fi in result.blocked if fi.item_id == stale_ref)
    assert blocked_50.adapter == AdapterCategory.WAIT
    assert any(INCOMPLETE_REASON in r for r in blocked_50.blocked_reasons)


def test_layer2_empty_spec_idea_is_classified_blocked():
    """An empty (NULL-equivalent) spec is treated as title-only too."""
    conn = make_test_db()
    item_num = 60
    insert_item(conn, item_num, title="Empty spec", status="idea", spec="")
    conn.commit()

    result = compute_frontier(conn, project_scope=["yoke"])
    blocked_ids = [fi.item_id for fi in result.blocked]
    assert f"YOK-{item_num}" in blocked_ids


def test_layer2_helper_recognises_title_only_row():
    """The shared heuristic agrees with the frontier classifier."""
    title_only = {"title": "Same shape", "spec": "# Same shape"}
    real_body = {
        "title": "Same shape",
        "spec": "# Same shape\n\nReal body content with multiple lines of detail.",
    }
    assert is_idea_body_incomplete(title_only) is True
    assert is_idea_body_incomplete(real_body) is False
