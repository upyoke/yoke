from __future__ import annotations

from yoke_core.domain import strategy_review_requests as reviews


class _ExistsConnection:
    def execute(self, _sql, _params):
        return self

    def fetchone(self):
        return (1,)


def test_strategy_review_adds_named_reviewer_with_role_fallback(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        reviews,
        "create_decision_request",
        lambda _conn, **kwargs: calls.append(kwargs) or (
            {"id": 71, "status": "pending"},
            True,
        ),
    )

    request, created = reviews.ensure_strategy_revision_review(
        _ExistsConnection(),
        project_id=10,
        slug="VISION",
        revision=4,
        originator_actor_id=1,
        reviewer_actor_id=3,
    )

    assert created is True
    assert request["id"] == 71
    assert calls[0]["named_actor_ids"] == [3]
    assert calls[0]["role_authorities"] == [
        reviews.RoleAuthority("project", 10, "owner"),
        reviews.RoleAuthority("project", 10, "operator"),
    ]


def test_strategy_review_without_named_reviewer_keeps_role_fallback(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        reviews,
        "create_decision_request",
        lambda _conn, **kwargs: calls.append(kwargs) or (
            {"id": 72, "status": "pending"},
            True,
        ),
    )

    reviews.ensure_strategy_revision_review(
        _ExistsConnection(),
        project_id=10,
        slug="VISION",
        revision=5,
        originator_actor_id=None,
    )

    assert calls[0]["named_actor_ids"] == []
