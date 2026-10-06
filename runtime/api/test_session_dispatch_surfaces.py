"""Retired session dispatch boundaries stay absent from current adapters."""

from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_sessions import SESSIONS_SUBCOMMAND_REGISTRY
from yoke_core.api.main import app
from yoke_core.api.service_client import COMMANDS


def test_session_dispatch_boundaries_are_absent():
    assert ("sessions", "offer") not in SESSIONS_SUBCOMMAND_REGISTRY
    assert ("sessions", "ownership-guard") not in SESSIONS_SUBCOMMAND_REGISTRY
    assert "session-offer" not in COMMANDS
    assert "ownership-guard" not in COMMANDS
    assert "/v1/sessions/offer" not in {route.path for route in app.routes}


def test_current_session_operations_remain_registered():
    assert ("sessions", "identity") in SESSIONS_SUBCOMMAND_REGISTRY
    assert ("sessions", "checkpoint") in SESSIONS_SUBCOMMAND_REGISTRY
    assert ("charge", "schedule") in SUBCOMMAND_REGISTRY
