"""Shared TestClient fixture for local-universe UI server tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yoke_core.ui import server as ui_server


_TOKEN = "test-session-token-value"


@pytest.fixture()
def ui_client():
    with TestClient(ui_server.create_ui_app(_TOKEN)) as client:
        yield client
