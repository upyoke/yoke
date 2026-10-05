"""Process acquisition, strategy writes, and release share project identity."""

from __future__ import annotations

import pytest

from runtime.api.domain._path_claims_test_helpers import seed_test_holder_session
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import claims_work, strategy_docs
from yoke_core.domain.handlers._strategy_docs_test_helpers import (
    SEED_CONTENT,
    SEED_UPDATED_AT,
    seed_docs,
)
from yoke_core.domain.yoke_function_dispatch_claims_resolve import (
    session_claim_id_for_target,
)


@pytest.fixture
def claim_db(tmp_path, monkeypatch):
    # These sessions model live holders; stale-session cleanup is a separate gate.
    monkeypatch.setattr(
        "yoke_core.domain.sessions.clean_stale_harness_sessions", lambda conn: None
    )
    with init_test_db(tmp_path) as db_path:
        with connect_test_db(db_path) as conn:
            seed_test_holder_session(conn, "strategy-holder")
            seed_test_holder_session(conn, "feed-holder")
            seed_docs(conn)
            conn.commit()
        yield db_path


def _acquire(project, *, process="STRATEGIZE", session="strategy-holder", options=None):
    return claims_work.handle_acquire(
        FunctionCallRequest(
            function="claims.work.acquire",
            actor=ActorContext(session_id=session),
            target=TargetRef(kind="global"),
            payload={
                "target": {
                    "kind": "process",
                    "process_key": process,
                    "project": project,
                }
            },
            options=options or {},
        )
    )


@pytest.mark.parametrize("project", ["1", "yoke"])
def test_acquire_allows_strategy_replace(claim_db, project):
    acquired = _acquire(project)
    assert acquired.primary_success, acquired.error
    assert (
        acquired.result_payload["scope"]["conflict_group"]
        == "strategy-control-plane:yoke"
    )
    replaced = strategy_docs.handle_doc_replace(
        FunctionCallRequest(
            function="strategy.doc.replace",
            actor=ActorContext(session_id="strategy-holder"),
            target=TargetRef(kind="global", project_id=project),
            payload={
                "slug": "MISSION",
                "content": SEED_CONTENT["MISSION"] + "\nUpdated.\n",
                "base_updated_at": SEED_UPDATED_AT,
            },
        )
    )
    assert replaced.primary_success, replaced.error


@pytest.mark.parametrize("first,second", [("1", "yoke"), ("yoke", "1")])
@pytest.mark.parametrize(
    "process,other", [("STRATEGIZE", "FEED"), ("FEED", "STRATEGIZE")]
)
def test_processes_exclude_each_other_across_project_references(
    claim_db, first, second, process, other
):
    assert _acquire(first, process=process).primary_success
    refused = _acquire(second, process=other, session="feed-holder")
    assert not refused.primary_success
    assert refused.error.code == "already_claimed", refused.error


@pytest.mark.parametrize("acquire_ref,release_ref", [("1", "yoke"), ("yoke", "1")])
def test_release_by_name_finds_canonical_claim(claim_db, acquire_ref, release_ref):
    acquired = _acquire(acquire_ref)
    assert acquired.primary_success, acquired.error
    claim_id = session_claim_id_for_target(
        TargetRef(kind="global"),
        "strategy-holder",
        process_key="STRATEGIZE",
        project=release_ref,
    )
    assert claim_id == acquired.result_payload["claim_id"]
    released = claims_work.handle_release(
        FunctionCallRequest(
            function="claims.work.release",
            actor=ActorContext(session_id="strategy-holder"),
            target=TargetRef(kind="global", claim_id=claim_id),
            payload={"reason": "finished"},
        )
    )
    assert released.primary_success, released.error
    assert _acquire(release_ref, process="FEED", session="feed-holder").primary_success


def test_unknown_project_refuses_without_acquiring(claim_db):
    refused = _acquire("missing-project")
    assert not refused.primary_success
    assert refused.error.code == "project_not_found"
    assert "--project" in refused.error.message


@pytest.mark.parametrize(
    "options", [{"visible_project_ids": [1]}, {"authorized_project_id": 1}]
)
def test_ambiguous_slug_uses_authorized_project_context(claim_db, options):
    with connect_test_db(claim_db) as conn:
        org = conn.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('other', 'Other', '2026-01-01T00:00:00Z') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "UPDATE projects SET org_id = %s, slug = 'yoke' WHERE id = 2", (org,)
        )
        conn.commit()
    acquired = _acquire("yoke", options=options)
    assert acquired.primary_success, acquired.error
    assert (
        acquired.result_payload["scope"]["conflict_group"]
        == "strategy-control-plane:yoke"
    )
