"""Link repair keeps old issues untouched and refuses unverified targets."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from runtime.api.conftest import insert_item, insert_epic_task
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import github_rest
from yoke_core.domain.handlers import items_github_link as handler
from yoke_cli.commands.adapters import items_github_sync as adapter


@pytest.fixture
def link_db(monkeypatch):
    with test_database() as conn:
        insert_item(conn, id=37, project="externalwebapp", github_issue="#420")
        insert_epic_task(
            conn, epic_id=37, task_num=1, title="Task", github_issue="#421"
        )

        @contextmanager
        def connect():
            yield conn

        monkeypatch.setattr(handler.db_helpers, "connect", connect)
        yield conn


def request(**payload):
    return FunctionCallRequest(
        function="items.github_link",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="item", item_id=37),
        payload=payload,
    )


@pytest.mark.parametrize("task_num,previous", [(None, "#420"), (1, "#421")])
def test_unlink_needs_no_github_access(link_db, monkeypatch, task_num, previous):
    remote = Mock(side_effect=AssertionError("unlink must stay local"))
    monkeypatch.setattr(handler.github_rest, "get_issue", remote)
    result = handler.handle_github_link(request(task_num=task_num))
    assert result.primary_success
    assert result.result_payload["previous_issue"] == previous
    assert result.result_payload["github_issue"] == ""
    remote.assert_not_called()
    assert (
        handler.handle_github_link(request(task_num=task_num)).result_payload["changed"]
        is False
    )


def test_relink_verifies_project_and_changes_only_link(link_db, monkeypatch):
    read = Mock(return_value=github_rest.Issue(7, "Chosen issue", "OPEN"))
    monkeypatch.setattr(handler.github_rest, "get_issue", read)
    result = handler.handle_github_link(request(issue_number=7))
    assert result.primary_success
    read.assert_called_once_with(project="externalwebapp", number=7)
    assert (
        link_db.execute("SELECT github_issue FROM items WHERE id = 37").fetchone()[0]
        == "#7"
    )
    assert (
        link_db.execute(
            "SELECT github_issue FROM epic_tasks WHERE epic_id = 37"
        ).fetchone()[0]
        == "#421"
    )


@pytest.mark.parametrize(
    "issue", [None, github_rest.Issue(7, "PR", "OPEN", is_pull_request=True)]
)
def test_absent_issue_or_pull_request_preserves_link(link_db, monkeypatch, issue):
    monkeypatch.setattr(handler.github_rest, "get_issue", lambda **_: issue)
    result = handler.handle_github_link(request(issue_number=7))
    assert result.error.code == "github_issue_not_found"
    assert (
        link_db.execute("SELECT github_issue FROM items WHERE id = 37").fetchone()[0]
        == "#420"
    )


def test_transport_failure_preserves_link_and_teaches_recovery(link_db, monkeypatch):
    monkeypatch.setattr(
        handler.github_rest,
        "get_issue",
        Mock(side_effect=github_rest.RestTransportError("offline", status=500)),
    )
    result = handler.handle_github_link(request(issue_number=7))
    assert result.error.code == "github_issue_unverified"
    assert "yoke github status" in result.error.message
    assert (
        link_db.execute("SELECT github_issue FROM items WHERE id = 37").fetchone()[0]
        == "#420"
    )


@pytest.mark.parametrize(
    "payload", [{"issue_number": 0}, {"issue_number": True}, {"task_num": -1}]
)
def test_invalid_numbers_refuse_without_mutation(link_db, payload):
    assert (
        handler.handle_github_link(request(**payload)).error.code == "invalid_payload"
    )


def test_unknown_task_refuses(link_db):
    assert (
        handler.handle_github_link(request(task_num=9)).error.code == "task_not_found"
    )


def test_registered_contract_requires_claim_and_serving_floor():
    contract = handler.REGISTRATIONS[0]
    assert contract["claim_required_kind"] == "item"
    assert contract["minimum_serving_version"] == "next-release"


def test_adapter_dispatches_explicit_unlink(monkeypatch):
    dispatch = Mock(return_value=0)
    monkeypatch.setattr(adapter, "dispatch_and_emit", dispatch)
    assert adapter.items_github_link(["TEST-1", "--unlink", "--task-num", "2"]) == 0
    assert dispatch.call_args.kwargs["payload"] == {"issue_number": None, "task_num": 2}
    assert adapter.items_github_link(["TEST-1"]) == 2


def test_registrar_installs_link_contract(monkeypatch):
    from yoke_core.domain import yoke_function_registry as registry
    from yoke_core.domain.handlers import _register_items_github_sync
    from yoke_core.domain.yoke_function_registry import RegistryEntry

    entries = {}
    monkeypatch.setattr(
        registry,
        "register",
        lambda **kwargs: entries.setdefault(
            kwargs["function_id"],
            RegistryEntry(**{"emitted_event_names": (), **kwargs}),
        ),
    )
    _register_items_github_sync.register(registry)
    assert entries["items.github_link"].claim_required_kind == "item"
