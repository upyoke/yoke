"""Live-acceptance roster surface and version-floor checks."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_roster import (
    validated_registration,
)


class _RosterClient:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def call(self, args: list[str]) -> dict[str, Any]:
        assert args == [
            "sessions",
            "list",
            "--project",
            "yoke",
            "--session",
            "session-1",
        ]
        return {"rows": [self.row]}


def _registration(*, surface: str, version: str) -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "project": "yoke",
        "executor_surface": surface,
        "executor_version": version,
        "mode": "wait",
        "claims": [],
        "current_item": None,
        "liveness": "active",
    }


def _validate(*, surface: str = "claude-cli", version: str) -> dict[str, Any]:
    return validated_registration(
        _RosterClient(_registration(surface=surface, version=version)),
        project="yoke",
        cell=AcceptanceCell("claude-cli", "2.1.238", "create"),
        session_id="session-1",
    )


def test_roster_accepts_a_newer_patch_version() -> None:
    row = _validate(version="2.1.239")

    assert row["executor_version"] == "2.1.239"


@pytest.mark.parametrize("version", ("2.1.237", "not-a-version"))
def test_roster_rejects_versions_below_or_outside_the_floor(version: str) -> None:
    with pytest.raises(AcceptanceContractError) as caught:
        _validate(version=version)

    assert caught.value.code == "registration_version_mismatch"


def test_roster_keeps_the_surface_kind_strict() -> None:
    with pytest.raises(AcceptanceContractError) as caught:
        _validate(surface="claude-desktop", version="99.0.0")

    assert caught.value.code == "registration_surface_mismatch"
