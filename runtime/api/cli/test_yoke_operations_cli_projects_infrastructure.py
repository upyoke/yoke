"""Dispatch coverage for project infrastructure inventory reads."""

import pytest

from runtime.api.cli.test_yoke_operations_cli_projects import (
    _CAPTURED_REQUESTS,
    _run,
    _stub_ok,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def test_dispatches_metadata_inventory_read() -> None:
    rc = _run(
        _stub_ok,
        "projects",
        "infrastructure",
        "list",
        "--project",
        "externalwebapp",
    )
    assert rc == 0
    req = _CAPTURED_REQUESTS[-1]
    assert req.function == "projects.infrastructure.list"
    assert req.target.kind == "global"
    assert req.payload == {"project": "externalwebapp"}


def test_missing_project_returns_two() -> None:
    rc = _run(_stub_ok, "projects", "infrastructure", "list")
    assert rc == 2
