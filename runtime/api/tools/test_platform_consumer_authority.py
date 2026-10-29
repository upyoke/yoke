"""Scoped consumer credentials bind only to the run owner endpoint."""

import pytest
from runtime.api.tools import require_platform_consumer_compatibility as gate


@pytest.mark.parametrize("owner", ["stage", "prod"])
def test_consumer_bootstrap_uses_run_owner_endpoint(monkeypatch, owner):
    endpoint = f"https://{owner}.example/api/orgs/team"
    calls = []
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")
    monkeypatch.setenv("YOKE_API_BASE", endpoint)
    monkeypatch.setattr(
        gate, "_yoke", lambda argv, **kwargs: calls.append(argv) or (0, "", "")
    )
    assert gate.bind_consumer_authority() == ""
    assert calls[0][calls[0].index("--api-url") + 1] == endpoint


@pytest.mark.parametrize(
    "endpoint", ["", "http://example.com", "https://secret@example.com"]
)
def test_consumer_bootstrap_refuses_missing_or_unsafe_endpoint(monkeypatch, endpoint):
    calls = []
    monkeypatch.setenv(gate.CONSUMER_TOKEN_ENV, "scoped-token")
    monkeypatch.setenv("YOKE_API_BASE", endpoint)
    monkeypatch.setattr(
        gate, "_yoke", lambda argv, **kwargs: calls.append(argv) or (0, "", "")
    )
    assert gate.bind_consumer_authority().startswith(
        "release_control_endpoint_unavailable:"
    )
    assert calls == []
