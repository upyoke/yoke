"""Ouroboros list readers attach the checkout's mapped project client-side."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


def test_entry_list_attaches_cwd_project() -> None:
    with patch(
        "yoke_cli.commands.adapters.misc.client_project_context",
        return_value="1",
    ) as resolver:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "ouroboros", "entry", "list", "--unreviewed",
            "--count",
        )
    assert rc == 0
    resolver.assert_called_once_with(None)
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.entry.list"
    assert req.payload == {"unreviewed": True, "count": True, "project": "1"}


def test_entry_list_explicit_project_wins() -> None:
    with patch(
        "yoke_cli.commands.adapters.misc.client_project_context",
        side_effect=lambda explicit: explicit or "1",
    ) as resolver:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "entry", "list", "--project", "externalwebapp",
        )
    assert rc == 0
    resolver.assert_called_once_with("externalwebapp")
    assert _CAPTURED_REQUESTS[-1].payload == {"project": "externalwebapp"}


def test_entry_list_omits_project_from_unmapped_directory() -> None:
    with patch(
        "yoke_cli.commands.adapters.misc.client_project_context",
        return_value=None,
    ):
        rc = _run_with_dispatch(_stub_dispatch_ok, "ouroboros", "entry", "list")
    assert rc == 0
    assert "project" not in _CAPTURED_REQUESTS[-1].payload


def test_field_note_list_attaches_cwd_project() -> None:
    with patch(
        "yoke_cli.commands.adapters.ouroboros_field_note.client_project_context",
        return_value="1",
    ) as resolver:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "field-note", "list", "--unreviewed", "--count",
        )
    assert rc == 0
    resolver.assert_called_once_with(None)
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.list"
    assert req.payload == {
        "category_prefix": "field-note-",
        "unreviewed": True,
        "count": True,
        "project": "1",
    }


def test_field_note_list_omits_project_from_unmapped_directory() -> None:
    with patch(
        "yoke_cli.commands.adapters.ouroboros_field_note.client_project_context",
        return_value=None,
    ):
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "ouroboros", "field-note", "list",
        )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "ouroboros.field_note.list"
    assert req.payload == {"category_prefix": "field-note-"}
