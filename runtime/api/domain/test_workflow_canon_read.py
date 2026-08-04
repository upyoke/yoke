"""Serving the code-owned canon so a client can compare against it.

The canon is code, not rows. A universe comparing what it runs against what
Yoke published therefore cannot reach the other side with a database read,
which is the whole reason this read exists.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.handlers.workflows_versioning import (
    handle_workflows_canon_get,
)


def _request(payload: dict, kind: str = "global") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="workflows.canon.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind=kind),
        payload=payload,
    )


def test_omitting_the_version_serves_the_newest_generation():
    outcome = handle_workflows_canon_get(_request({"workflow_id": "issue"}))

    assert outcome.primary_success
    newest = canon_generations("issue")[-1]
    assert outcome.result_payload["canon_version"] == newest.canon_version
    assert outcome.result_payload["definition_digest"] == newest.digest
    assert outcome.result_payload["is_newest"] is True
    assert outcome.result_payload["definition"]["stages"]


def test_an_older_generation_is_served_and_marked_as_such():
    generations = canon_generations("dash")
    outcome = handle_workflows_canon_get(
        _request({"workflow_id": "dash", "canon_version": 1}),
    )

    assert outcome.primary_success
    assert outcome.result_payload["canon_version"] == 1
    assert outcome.result_payload["definition_digest"] == generations[0].digest
    assert outcome.result_payload["is_newest"] is False


def test_an_unknown_workflow_is_typed_not_found():
    outcome = handle_workflows_canon_get(_request({"workflow_id": "nope"}))

    assert not outcome.primary_success
    assert outcome.error.code == "not_found"
    assert "no published canon" in outcome.error.message


def test_an_unknown_generation_is_typed_not_found():
    outcome = handle_workflows_canon_get(
        _request({"workflow_id": "issue", "canon_version": 9999}),
    )

    assert not outcome.primary_success
    assert outcome.error.code == "not_found"


def test_the_read_requires_a_global_target():
    outcome = handle_workflows_canon_get(
        _request({"workflow_id": "issue"}, kind="item"),
    )

    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"


def test_the_read_is_reachable_from_the_dashboard():
    """The diff runs in the browser, so the proxy has to allow the read."""
    from yoke_core.ui.function_proxy import UI_READ_FUNCTION_ALLOWLIST

    assert "workflows.canon.get" in UI_READ_FUNCTION_ALLOWLIST
