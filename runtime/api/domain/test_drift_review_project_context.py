"""Drift diagnostics never invent a project for an empty caller scope."""

import pytest

from yoke_core.domain import drift_review_assess as review


@pytest.mark.parametrize("scope", [None, [], "", " "])
def test_empty_drift_scope_does_not_query_a_project(monkeypatch, scope):
    def forbidden(*args, **kwargs):
        raise AssertionError("empty scope queried an invented project")

    monkeypatch.setattr(review, "_get_checkpoint_start", forbidden)
    monkeypatch.setattr(review, "_get_delivered_items", forbidden)
    assert review.assess_post_delivery_drift(object(), scope) is None


def test_drift_scope_queries_only_the_callers_projects(monkeypatch):
    queried = []
    monkeypatch.setattr(review, "_get_checkpoint_start", lambda conn, project: None)
    monkeypatch.setattr(
        review,
        "_get_delivered_items",
        lambda conn, project, checkpoint: queried.append(project) or [],
    )
    assert review.assess_post_delivery_drift(object(), [7, 42]) is None
    assert queried == ["7", "42"]
