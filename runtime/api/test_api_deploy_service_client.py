"""Service-client charge-frontier and charge-schedule tests."""

from __future__ import annotations

import json
import os

from runtime.api.test_api_deploy_test_helpers import (
    frontier_db,  # noqa: F401 — re-exported pytest fixture
)
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)


def _postgres_subprocess_env() -> dict:
    """Child env inheriting the per-test Postgres authority."""
    env = os.environ.copy()
    env.pop("YOKE_DB", None)
    return _with_source_pythonpath(env)


# ---------------------------------------------------------------------------
# Service client charge-frontier tests (Task 003 AC-4)
# ---------------------------------------------------------------------------


class TestServiceClientChargeFrontier:
    """Tests for service_client.py charge-frontier command."""

    def test_charge_frontier_prints_json(self, frontier_db):
        """AC-4: charge-frontier outputs valid JSON (direct DB, not HTTP)."""
        import subprocess

        env = _postgres_subprocess_env()

        result = subprocess.run(
            _service_client_cmd([
                "charge-frontier",
            ]),
            env=env,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "runnable" in data
        assert "blocked" in data
        assert "frozen" in data
        assert "wip_cap" in data
        assert "wip_active" in data
        assert "conduct_eligible" in data

    def test_charge_frontier_project_filter(self, frontier_db):
        """Project filter works in service client."""
        import subprocess

        env = _postgres_subprocess_env()

        result = subprocess.run(
            _service_client_cmd([
                "charge-frontier",
                "--project", "externalwebapp",
            ]),
            env=env,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        runnable_ids = [item["item_id"] for item in data["runnable"]]
        assert "YOK-24" in runnable_ids
        assert "YOK-20" not in runnable_ids

    def test_charge_frontier_wip_cap(self, frontier_db):
        """WIP cap parameter works in service client."""
        import subprocess

        env = _postgres_subprocess_env()

        result = subprocess.run(
            _service_client_cmd([
                "charge-frontier",
                "--wip-cap", "2",
            ]),
            env=env,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["wip_cap"] == 2

    def test_charge_frontier_invalid_wip_cap(self, frontier_db):
        """Invalid wip-cap returns error."""
        import subprocess

        env = _postgres_subprocess_env()

        result = subprocess.run(
            _service_client_cmd([
                "charge-frontier",
                "--wip-cap", "abc",
            ]),
            env=env,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1


# ---------------------------------------------------------------------------
# Service client charge-schedule tests
# ---------------------------------------------------------------------------


class TestServiceClientChargeSchedule:
    """Tests for service_client.py charge-schedule command."""

    def test_charge_schedule_prints_downstream_depth(self, frontier_db):
        """charge-schedule returns scheduled steps with downstream_depth."""
        import subprocess

        env = _postgres_subprocess_env()

        result = subprocess.run(
            _service_client_cmd([
                "charge-schedule",
            ]),
            env=env,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data["ranked_steps"]) > 0
        assert "downstream_depth" in data["ranked_steps"][0]
