"""CLI payload contract for migration-content identity verification."""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _stub_dispatch_ok,
)
from yoke_contracts.migration_content_identity import FUNCTION_ID


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_adapter_dispatches_a_validated_global_candidate_set() -> None:
    entries = [{"name": "0015_entry", "content_sha256": "a" * 64}]

    rc, _out, err = _run_capture(
        _stub_dispatch_ok,
        "migration",
        "content-identity",
        "verify",
        "--entries-json",
        json.dumps(entries),
    )

    assert rc == 0
    assert err == ""
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == FUNCTION_ID
    assert request.target.kind == "global"
    assert request.payload == {"entries": entries}


def test_adapter_refuses_duplicate_names_before_dispatch() -> None:
    entries = [
        {"name": "0015_entry", "content_sha256": "a" * 64},
        {"name": "0015_entry", "content_sha256": "b" * 64},
    ]

    rc, _out, err = _run_capture(
        _stub_dispatch_ok,
        "migration",
        "content-identity",
        "verify",
        "--entries-json",
        json.dumps(entries),
    )

    assert rc == 2
    assert "unique names" in err
    assert not _CAPTURED_REQUESTS
