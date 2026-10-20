"""Keep every test's uv commands off the environment running the suite.

The source runner starts pytest with ``UV_PROJECT_ENVIRONMENT`` naming the
checkout's own ``.venv``. A test that inherits it and runs ``uv sync`` or
``uv run`` for a fixture project installs that fixture's lock into the
running environment, removing every package the suite needs mid-run. Each
test therefore starts without it, so uv uses the fixture project's own
``.venv``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_running_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
