"""A branch head read answers where the project's repository binding is.

The release bridge has no checkout of the consumer and no credential for its
repository, yet must know whether the consumer trunk still names the commit a
proof was taken at — and, when it moved, whether it only moved forward.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS
from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.function_authz_scope_release_ci import RELEASE_CI_AUTHZ_BY_ID
from yoke_core.domain.handlers import github_branch_head as handler

SINCE = "b" * 40
HEAD = "c" * 40


class _Resolved:
    repo = "upyoke/platform"
    token = "t"


class _Source:
    def __init__(self, head: str, contains: Any) -> None:
        self.head = head
        self.contains = contains
        self.asked: list[tuple[str, str]] = []

    def resolve_commit(self, ref: str) -> str:
        assert ref == "main"
        return self.head

    def contains_commit(self, candidate: str, commit: str) -> Optional[bool]:
        self.asked.append((candidate, commit))
        if isinstance(self.contains, Exception):
            raise self.contains
        return self.contains


def _read(monkeypatch: pytest.MonkeyPatch, source: _Source, since: str = SINCE):
    monkeypatch.setattr(
        handler,
        "_validate_and_resolve_auth",
        lambda request, model, function_id, *, required_permissions: (
            model.model_validate(request.payload or {}),
            _Resolved(),
            None,
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_carried_work_repository."
        "RepositoryProviderSource",
        lambda repo, token: source,
    )
    payload = {"project": "platform", "branch": "main"}
    if since:
        payload["since"] = since
    return handler.handle_branch_head(
        _request(
            function=handler.FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


@pytest.mark.parametrize(
    ("head", "contains", "relation"),
    [
        (SINCE, None, handler.RELATION_IDENTICAL),
        (HEAD, True, handler.RELATION_DESCENDANT),
        (HEAD, False, handler.RELATION_NOT_DESCENDANT),
    ],
)
def test_the_head_and_its_ancestry_over_since(
    monkeypatch: pytest.MonkeyPatch,
    head: str,
    contains: Any,
    relation: str,
) -> None:
    source = _Source(head, contains)

    outcome = _read(monkeypatch, source)

    assert outcome.primary_success
    assert outcome.result_payload["head_sha"] == head
    assert outcome.result_payload["relation"] == relation
    assert outcome.result_payload["repo"] == "upyoke/platform"
    # The head contains ``since`` exactly when ``since`` is its ancestor.
    assert source.asked == ([] if head == SINCE else [(HEAD, SINCE)])


def test_without_since_only_the_head_is_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _Source(HEAD, None)

    outcome = _read(monkeypatch, source, since="")

    assert outcome.result_payload["head_sha"] == HEAD
    assert outcome.result_payload["relation"] == ""
    assert source.asked == []


def test_an_unresolvable_branch_is_a_named_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _read(monkeypatch, _Source("", None))

    assert not outcome.primary_success
    assert "resolved no commit" in outcome.error.message


def test_an_unreadable_ancestry_is_a_named_failure_not_a_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = CarriedWorkSourceUnavailable("repository_read_failed", "retry later")

    outcome = _read(monkeypatch, _Source(HEAD, failure))

    assert not outcome.primary_success
    assert "repository_read_failed" in outcome.error.message


def test_the_read_is_floored_and_open_to_the_release_identity() -> None:
    (registration,) = handler.REGISTRATIONS

    assert registration["minimum_serving_version"] == "next-release"
    assert FUNCTION_MINIMUM_SERVING_VERSIONS[handler.FUNCTION_ID] == "next-release"
    assert handler.FUNCTION_ID in RELEASE_CI_AUTHZ_BY_ID
