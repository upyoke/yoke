# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract

EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


def _walker(executor: str, identities: list[str] | None = None, conn=None) -> dict:
    bundle = {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": EXECUTION_ID,
        "subject": {"item_id": 4550, "deployment_run_id": None},
        "execution_target": {
            "project": {"id": 1, "slug": "yoke"},
            "environment": {"name": "stage"},
            "tenant": {"slug": "yoke"},
            "endpoints": {"base_url": "https://stage.example"},
        },
        "execution_target_digest": "e" * 64,
        "cases": [
            {
                "requirement_id": 18152,
                "capture_runner": "agent_mission",
                "capture_run_id": 991,
                "executor": executor,
                "method_config": {
                    "browser_identities": identities or [],
                    "os": "macos",
                },
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }
    return agent_mission_dispatch_contract(bundle, conn=conn)["walker_dispatches"][0]
