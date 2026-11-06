"""Only a landed declaration may mutate shared repository rules."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.api.merge_queue_live_drift_test_support import DECLARED
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import db_backend, db_helpers, github_merge_queue_rest as rest
from yoke_core.domain import merge_queue_declaration_apply, project_github_auth
from yoke_core.domain.handlers.github_merge_queue_apply import handle_merge_queue_apply


@pytest.fixture
def gate(monkeypatch):
    state = {"landed": deepcopy(DECLARED), "reads": [], "permissions": []}

    def auth(project, **kwargs):
        state["permissions"].append(kwargs["required_permissions"])
        return SimpleNamespace(project="project", repo="example/project", token="t")

    def read(owner, repo, path, *, ref, token):
        state["reads"].append((path, ref))
        return json.dumps(state["landed"])

    monkeypatch.setattr(project_github_auth, "resolve_project_github_auth", auth)
    monkeypatch.setattr(db_helpers, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda conn: True)
    monkeypatch.setattr(db_helpers, "query_scalar", lambda *a, **k: "release/stable")
    monkeypatch.setattr(rest, "fetch_file_text", read)
    apply = Mock(return_value={
        "preview": False, "owner": "example", "repo": "project",
        "ruleset_name": "merge-queue-main", "actions": [], "changed": True,
    })
    monkeypatch.setattr(merge_queue_declaration_apply, "apply_declaration", apply)
    state["apply"] = apply
    return state


def request(declaration=None, *, preview=False):
    return FunctionCallRequest(
        function="github.merge_queue.apply", version="v1",
        actor=ActorContext(actor_id=None, session_id="test-gate-apply"),
        target=TargetRef(kind="global"),
        payload={"project": "project", "declaration": declaration, "preview": preview},
    )


@pytest.mark.parametrize("operation", ["add", "remove", "rename"])
def test_unlanded_content_refuses_without_mutating_then_applies_after_landing(gate, operation):
    candidate = deepcopy(DECLARED)
    checks = candidate["ruleset"]["rules"][1]["parameters"]["required_status_checks"]
    if operation == "add":
        checks.append({"context": "new-check"})
    elif operation == "remove":
        checks.clear()
    else:
        checks[0]["context"] = "renamed-check"
    outcome = handle_merge_queue_apply(request(candidate))
    assert not outcome.primary_success
    assert outcome.error.code == "declaration_not_landed"
    assert "land the declaration change first, then apply" in outcome.error.message
    assert "two PRs" in outcome.error.message
    gate["apply"].assert_not_called()
    assert gate["reads"] == [(".yoke/merge-queue.json", "release/stable")]
    assert gate["permissions"] == [{"administration": "write", "contents": "read"}]

    gate["landed"] = candidate
    outcome = handle_merge_queue_apply(request(candidate))
    assert outcome.primary_success
    assert gate["apply"].call_args.args == (candidate,)


@pytest.mark.parametrize("preview", [False, True])
def test_apply_without_content_uses_gate_on_server_without_checkout(gate, preview):
    outcome = handle_merge_queue_apply(request(preview=preview))
    assert outcome.primary_success
    assert gate["reads"] == [(".yoke/merge-queue.json", "release/stable")]
    assert gate["apply"].call_args.args == (DECLARED,)


def test_preview_can_use_unlanded_content_without_gate_read(gate):
    candidate = deepcopy(DECLARED)
    candidate["repository"]["allow_auto_merge"] = False
    outcome = handle_merge_queue_apply(request(candidate, preview=True))
    assert outcome.primary_success
    assert gate["reads"] == []
    assert gate["apply"].call_args.args == (candidate,)
    assert gate["apply"].call_args.kwargs["preview"] is True


def test_missing_gate_declaration_refuses_without_mutating(gate, monkeypatch):
    monkeypatch.setattr(rest, "fetch_file_text", lambda *a, **k: None)
    outcome = handle_merge_queue_apply(request())
    assert not outcome.primary_success
    assert "gate_declaration_unverified" in outcome.error.message
    assert "Restore Contents: read" in outcome.error.message
    gate["apply"].assert_not_called()
