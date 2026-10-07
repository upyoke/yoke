"""Review subjects render independent storage keys into public commands."""

import pytest

from yoke_core.domain import qa_plan_review_subject as subjects


def test_review_subject_renders_join_keys_without_exposing_them(monkeypatch):
    connection = object()
    seen = []

    def render(conn, ids):
        assert conn is connection
        seen.extend(ids)
        return {7201: "ITEM-81", 9202: "EXT-19"}

    monkeypatch.setattr(subjects, "render_item_refs", render)
    subject = subjects.public_review_subject(
        connection,
        {
            "item_id": 7201,
            "deployment_member_item_id": 9202,
            "deployment_run_id": "run",
        },
    )
    assert seen == [7201, 9202]
    assert subject == {
        "public_ref": "ITEM-81",
        "deployment_member_public_ref": "EXT-19",
        "deployment_run_id": "run",
    }
    assert subjects.subject_flag(subject, None) == "--item ITEM-81"


def test_missing_review_identity_refuses_instead_of_emitting_a_command(monkeypatch):
    monkeypatch.setattr(subjects, "render_item_refs", lambda *args: {})
    with pytest.raises(ValueError, match="public_response_identity_unavailable"):
        subjects.public_review_subject(object(), {"item_id": 7201})


def test_non_item_review_subjects_keep_their_domain_selectors():
    assert (
        subjects.subject_flag({"deployment_run_id": "run"}, None)
        == "--deployment-run-id run"
    )
    assert (
        subjects.subject_flag(
            {"standalone_plan_id": 7}, {"project": {"slug": "example"}}
        )
        == "--project example"
    )
