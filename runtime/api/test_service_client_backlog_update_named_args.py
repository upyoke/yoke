"""Regression tests for AC-25: positional+named items update CLI shape.

Covers:
* ``normalize_update_args`` (pure normalization).
* ``cmd_execute_update_cli`` reaches the same ``backlog.execute_update``
  call for the positional form, the all-named form, and the mixed form
  ``--id <id> --field <field> --value <value>``.
* Raw body writes remain denied through the named-flag entrypoint.
* Structured-field writes via ``--id <id> <field> --stdin`` route to
  the structured-write dispatcher (not the value-string fast path).
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from yoke_core.api import service_client_backlog_update
from yoke_core.api.service_client_backlog_update_args import (
    has_named_update_flags,
    normalize_update_args,
)


# ---------- normalize_update_args (pure) ------------------------------------


def test_normalize_passthrough_when_no_named_flags():
    args = ["42", "title", "Hello", "--no-rebuild"]
    assert normalize_update_args(args) == args


def test_normalize_all_named():
    args = ["--id", "42", "--field", "title", "--value", "Hello"]
    assert normalize_update_args(args) == ["42", "title", "Hello"]


def test_normalize_positional_id_with_named_field_value():
    args = ["42", "--field", "title", "--value", "Hello"]
    assert normalize_update_args(args) == ["42", "title", "Hello"]


def test_normalize_named_id_with_positional_field_value():
    args = ["--id", "42", "spec", "--stdin"]
    assert normalize_update_args(args) == ["42", "spec", "--stdin"]


def test_normalize_preserves_global_flags_order():
    args = ["42", "--field", "status", "--value", "done", "--no-rebuild"]
    assert normalize_update_args(args) == ["42", "status", "done", "--no-rebuild"]


def test_normalize_mixed_named_id_with_value_only_flag():
    args = ["--id", "42", "spec", "--source", "test", "--stdin"]
    assert normalize_update_args(args) == [
        "42", "spec", "--source", "test", "--stdin",
    ]


def test_has_named_update_flags_detects_each_flag():
    assert has_named_update_flags(["--id", "1"]) is True
    assert has_named_update_flags(["--field", "title"]) is True
    assert has_named_update_flags(["--value", "x"]) is True
    assert has_named_update_flags(["1", "title", "x"]) is False


def test_normalize_tail_named_flag_without_value_passes_through():
    # Malformed input: --field at the tail with no value. The normalizer
    # must surface the bad token to the legacy parser rather than
    # silently dropping it.
    args = ["42", "--field"]
    out = normalize_update_args(args)
    assert "--field" in out


# ---------- cmd_execute_update_cli integration ------------------------------


def _patched_backlog():
    """Patch the underlying ``backlog.execute_update``.

    The CLI handler imports ``backlog`` lazily inside the function, so
    the patch must target the canonical domain module rather than a
    re-export on the CLI module.
    """
    return mock.patch(
        "yoke_core.domain.backlog.execute_update",
        autospec=True,
    )


def _set_mock_success(m):
    m.return_value = {"success": True, "updated_count": 1}


def test_cli_positional_form_still_works(capsys):
    with _patched_backlog() as m, mock.patch.dict(os.environ, {}, clear=False):
        _set_mock_success(m)
        rc = service_client_backlog_update.cmd_execute_update_cli(
            ["42", "title", "Hello"]
        )
    assert rc == 0
    call = m.call_args
    assert call.kwargs["item_id"] == 42
    assert call.kwargs["field"] == "title"
    assert call.kwargs["value"] == "Hello"


def test_cli_named_id_field_value_form():
    with _patched_backlog() as m, mock.patch.dict(os.environ, {}, clear=False):
        _set_mock_success(m)
        rc = service_client_backlog_update.cmd_execute_update_cli(
            ["--id", "42", "--field", "title", "--value", "Hello"]
        )
    assert rc == 0
    call = m.call_args
    assert call.kwargs["item_id"] == 42
    assert call.kwargs["field"] == "title"
    assert call.kwargs["value"] == "Hello"


def test_cli_positional_id_with_named_field_value():
    with _patched_backlog() as m, mock.patch.dict(os.environ, {}, clear=False):
        _set_mock_success(m)
        rc = service_client_backlog_update.cmd_execute_update_cli(
            ["42", "--field", "priority", "--value", "high"]
        )
    assert rc == 0
    call = m.call_args
    assert call.kwargs["item_id"] == 42
    assert call.kwargs["field"] == "priority"
    assert call.kwargs["value"] == "high"


def test_cli_raw_body_write_denied_through_named_flags(capsys):
    # AC-25 invariant: raw body writes must remain denied even when
    # reached via the new --id/--stdin entrypoint.
    rc = service_client_backlog_update.cmd_execute_update_cli(
        ["--id", "42", "body", "--stdin"]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "raw body writes" in captured.out


def test_cli_structured_field_write_routes_to_dispatcher():
    # AC-25 invariant: --id <id> <structured-field> --stdin still routes
    # through the function dispatcher, not the value-string fast path.
    dispatch_path = (
        "yoke_core.api.service_client_backlog_update."
        "_dispatch_structured_field_replace"
    )
    with mock.patch(dispatch_path, autospec=True) as dispatch_mock, \
         mock.patch("sys.stdin", io.StringIO("# spec content")):
        dispatch_mock.return_value = 0
        rc = service_client_backlog_update.cmd_execute_update_cli(
            ["--id", "42", "spec", "--stdin"]
        )
    assert rc == 0
    dispatch_mock.assert_called_once()
    call = dispatch_mock.call_args
    assert call.kwargs["item_id"] == 42
    assert call.kwargs["field"] == "spec"
    assert call.kwargs["content"] == "# spec content"
