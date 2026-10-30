"""A paused server is reachable for recovery, without ordinary readiness."""

import io
import json
from urllib.error import HTTPError

import pytest

from yoke_core.tools import self_host_handoff
from yoke_cli.config import server_connect
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError


@pytest.mark.parametrize(
    "code,reason,expected",
    [
        (503, "universe_source_paused", {"healthy": False, "paused": True}),
        (503, "database_unavailable", None),
        (403, "universe_source_paused", None),
    ],
)
def test_private_handoff_only_accepts_named_pause(code, reason, expected, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise HTTPError(
            "http://127.0.0.1/health",
            code,
            "unavailable",
            {},
            io.BytesIO(json.dumps({"error": {"code": reason}}).encode()),
        )

    monkeypatch.setattr(self_host_handoff.urllib.request, "urlopen", unavailable)
    assert self_host_handoff._health_status() == expected


def test_connect_reports_pause_and_explicit_resume(monkeypatch):
    def paused(*_args, **_kwargs):
        raise BoundedJsonHttpStatusError(
            503, {"error": {"code": "universe_source_paused"}}
        )

    monkeypatch.setattr(server_connect, "request_json", paused)
    with pytest.raises(server_connect.SourcePausedError, match="universe resume"):
        server_connect.verify_server_health("http://127.0.0.1:8765")
