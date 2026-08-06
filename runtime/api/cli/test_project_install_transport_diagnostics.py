"""Hosted project-refresh errors retain safe typed server detail."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.project_install import transport
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError


def test_https_bundle_error_surfaces_scrubbed_server_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args, **_kwargs):
        raise BoundedJsonHttpStatusError(
            500,
            {
                "error": {
                    "code": "INSTALL_BUNDLE_ERROR",
                    "message": (
                        "cursor agents source dir is missing (already-scrubbed-token)"
                    ),
                }
            },
        )

    monkeypatch.setattr(transport, "request_json", refuse)

    with pytest.raises(ProjectInstallError) as raised:
        transport._fetch_bundle_https(
            SimpleNamespace(
                api_url="https://api.example.test",
                token="already-scrubbed-token",
            ),
            41,
        )

    message = str(raised.value)
    assert "HTTP 500: cursor agents source dir is missing" in message
    assert "already-scrubbed-token" not in message
