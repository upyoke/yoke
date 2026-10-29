"""Feedback list scope is explicit and defaults to the whole universe."""

from unittest.mock import patch
from runtime.api.cli.test_yoke_operations_cli_dispatch import _CAPTURED_REQUESTS, _run_with_dispatch, _stub_dispatch_ok


def test_default_scope_remains_universe_in_a_checkout():
    with patch("yoke_cli.commands.adapters.feedback.client_project_context", return_value="1"):
        assert _run_with_dispatch(_stub_dispatch_ok, "feedback", "list", "--unreviewed", "--count") == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "ouroboros.field_note.list"
    assert request.payload == {"scope": "universe", "project": "1", "unreviewed": True, "count": True}


def test_project_scope_carries_the_selected_project():
    with patch("yoke_cli.commands.adapters.feedback.client_project_context", side_effect=lambda explicit: explicit):
        assert _run_with_dispatch(_stub_dispatch_ok, "feedback", "list", "--scope", "project", "--project", "example", "--category", "idea") == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"scope": "project", "project": "example", "category": "idea"}


def test_unscoped_read_works_without_a_checkout():
    with patch("yoke_cli.commands.adapters.feedback.client_project_context", return_value=None):
        assert _run_with_dispatch(_stub_dispatch_ok, "feedback", "list", "--scope", "unscoped") == 0
    assert _CAPTURED_REQUESTS[-1].payload == {"scope": "unscoped"}
