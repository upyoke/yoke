"""CLI dispatch preserves inline rules, named selection and shared Done."""

import json

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _run_capture,
    _stub_dispatch_ok,
)
from yoke_cli.operation_inventory import lookup


@pytest.fixture(autouse=True)
def reset():
    _CAPTURED_REQUESTS.clear()


def test_post_create_dispatches_typed_generic_fields():
    rules = [{"scope_kind": "project", "scope_id": 10, "role_name": "owner"}]
    assert (
        _run_with_dispatch(
            _stub_dispatch_ok,
            "inbox",
            "posts",
            "create",
            "--project-id",
            "10",
            "--title",
            "Review",
            "--body",
            "Details",
            "--source",
            "Form",
            "--rules",
            json.dumps(rules),
            "--fields",
            '{"contact":"person@example.test"}',
        )
        == 0
    )
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "inbox.posts.create"
    assert request.payload == {
        "project_id": 10,
        "title": "Review",
        "body": "Details",
        "source": "Form",
        "rules": rules,
        "fields": {"contact": "person@example.test"},
    }


def test_done_and_named_audiences_dispatch():
    assert _run_with_dispatch(_stub_dispatch_ok, "inbox", "posts", "done", "7") == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"post_id": 7}
    assert (
        _run_with_dispatch(_stub_dispatch_ok, "audiences", "list", "--project-id", "10")
        == 0
    )
    assert _CAPTURED_REQUESTS[-1].function == "audiences.list"
    assert (
        _run_with_dispatch(
            _stub_dispatch_ok,
            "audiences",
            "create",
            "--project-id",
            "10",
            "--name",
            "Owners",
            "--rules",
            '[{"scope_kind":"project","scope_id":10}]',
        )
        == 0
    )
    assert _CAPTURED_REQUESTS[-1].payload["name"] == "Owners"
    assert lookup("yoke inbox posts done").status == "wrapped"


def test_invalid_json_or_missing_audience_never_dispatches():
    rc, _, _ = _run_capture(
        _stub_dispatch_ok,
        "audiences",
        "create",
        "--project-id",
        "10",
        "--name",
        "Team",
        "--rules",
        "invalid-json",
    )
    assert rc == 2 and not _CAPTURED_REQUESTS
    rc, _, _ = _run_capture(
        _stub_dispatch_ok,
        "inbox",
        "posts",
        "create",
        "--project-id",
        "10",
        "--title",
        "Review",
        "--body",
        "Details",
        "--source",
        "Form",
    )
    assert rc == 2 and not _CAPTURED_REQUESTS
