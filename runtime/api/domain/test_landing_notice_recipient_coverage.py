"""Item notices use document coverage and ignore ended claim holders."""

import json
from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    seed_project,
    seed_session,
    seed_strategy_doc,
)
from runtime.api.domain.test_steering_scope_membership import _link, _seed_item
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import _claim
from yoke_core.domain import merge_queue_landing_notice as notice


def _seat(conn, session, project=PROJECT_ALPHA, document=None):
    seed_session(conn, session, project)
    scope = {"project_id": project}
    if document:
        scope["document"] = document
    _claim(
        conn, session_id=session, target_kind="steering", scope_json=json.dumps(scope)
    )


def _world(conn):
    seed_project(conn, PROJECT_ALPHA, "alpha")
    seed_project(conn, PROJECT_BETA, "beta")
    for document in ("DOC-A", "DOC-B", "NO-SEAT"):
        seed_strategy_doc(conn, PROJECT_ALPHA, document)
    for item in range(9101, 9106):
        _seed_item(conn, item)
    _link(conn, 9101, "DOC-B")
    _link(conn, 9103, "NO-SEAT")
    _link(conn, 9104, "DOC-A")
    _seat(conn, "whole-project")
    _seat(conn, "document-b", document="DOC-B")
    _seat(conn, "document-a", document="DOC-A")
    _seat(conn, "other-project", project=PROJECT_BETA, document="NO-SEAT")


def test_notices_choose_the_covering_document_not_the_newest_claim(test_db):
    _world(test_db)
    resolve = lambda item: notice.resolve_lane_recipient(
        test_db, item_id=item, project_id=PROJECT_ALPHA
    )
    assert resolve(9101) == ("document-b", 1, notice.STEERING)
    assert resolve(9102) == ("whole-project", 1, notice.STEERING)
    assert resolve(9103) == ("", 0, "")
    assert resolve(9104) == ("document-a", 1, notice.STEERING)


def test_ended_holder_is_skipped_but_explicit_owner_keeps_native_resume(test_db):
    _world(test_db)
    seed_session(test_db, "ended-holder", PROJECT_ALPHA)
    _claim(
        test_db,
        session_id="ended-holder",
        target_kind="item",
        scope_json=json.dumps({"item_id": 9101}),
    )
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=CURRENT_TIMESTAMP WHERE session_id=%s",
        ("ended-holder",),
    )
    assert notice.resolve_lane_recipient(
        test_db, item_id=9101, project_id=PROJECT_ALPHA
    ) == ("document-b", 1, notice.STEERING)
    assert notice.resolve_lane_recipient(
        test_db, item_id=9101, project_id=PROJECT_ALPHA, owner_session_id="ended-holder"
    ) == ("ended-holder", 1, notice.HOLDER)


def test_batch_agrees_with_individual_resolution_and_reads_membership_once(test_db):
    _world(test_db)
    seed_session(test_db, "live-holder", PROJECT_ALPHA)
    _claim(
        test_db,
        session_id="live-holder",
        target_kind="item",
        scope_json=json.dumps({"item_id": 9103}),
    )
    test_db.execute(
        "UPDATE harness_sessions SET actor_id=NULL WHERE session_id=%s",
        ("document-a",),
    )
    ids = list(range(9101, 9106))
    expected = {
        item
        for item in ids
        if notice.resolve_lane_recipient(
            test_db, item_id=item, project_id=PROJECT_ALPHA
        )[0]
    }
    with patch.object(
        notice, "live_steering_claims", wraps=notice.live_steering_claims
    ) as claims:
        with patch.object(
            notice, "item_document_links", wraps=notice.item_document_links
        ) as links:
            assert (
                notice.addressable_items(
                    test_db, item_ids=ids, project_id=PROJECT_ALPHA
                )
                == expected
                == {9101, 9102, 9103, 9105}
            )
    claims.assert_called_once_with(test_db)
    links.assert_called_once_with(test_db, ids)


def test_batch_does_not_fall_back_when_holder_has_no_actor(test_db):
    _world(test_db)
    seed_session(test_db, "actorless-holder", PROJECT_ALPHA)
    _claim(
        test_db,
        session_id="actorless-holder",
        target_kind="item",
        scope_json=json.dumps({"item_id": 9102}),
    )
    test_db.execute(
        "UPDATE harness_sessions SET actor_id=NULL WHERE session_id=%s",
        ("actorless-holder",),
    )
    assert notice.resolve_lane_recipient(
        test_db, item_id=9102, project_id=PROJECT_ALPHA
    ) == ("", 0, "")
    assert (
        notice.addressable_items(test_db, item_ids=[9102], project_id=PROJECT_ALPHA)
        == set()
    )
