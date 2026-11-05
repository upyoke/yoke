# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import shutil

from datetime import timedelta

from yoke_contracts.timestamps import format_instant, utc_now

import pytest

from runtime.api.domain.webapp_runner_github_broker_test_support import (
    _environment,
    _run_driver,
    _write_node_fixture,
)

INSTANCE_ID = "i-0123456789abcdef0"

RUNNER_NAME = f"yoke-github-actions-{INSTANCE_ID}"


def _parameters(
    *,
    idle_since: str | None = None,
    failures: int = 0,
    online_instance_id: str = "",
    queue_activity: str = "initial",
    marker_state: str | None = "ready",
    marker_age_seconds: int = 600,
    progress_event: dict | None = None,
    completion_event: dict | None = None,
) -> str:
    values = {
        "/fleet/lifecycle-state": json.dumps(
            {
                "idle_since": idle_since,
                "queue_activity": "initial",
                "bootstrap_failures": failures,
                "online_instance_id": online_instance_id,
                "idle_by_instance": {},
            }
        ),
        "/fleet/queue-activity": queue_activity,
        "/fleet/runner-progress": json.dumps(
            progress_event
            or {
                "action": "none",
                "runner_name": "",
                "job_id": "",
                "at": None,
            }
        ),
        "/fleet/runner-completion": json.dumps(
            completion_event
            or {
                "action": "none",
                "runner_name": "",
                "job_id": "",
                "at": None,
            }
        ),
    }
    if marker_state is not None:
        values[f"/fleet/bootstrap/{INSTANCE_ID}"] = json.dumps(
            {
                "state": marker_state,
                "at": format_instant(utc_now() - timedelta(seconds=marker_age_seconds)),
            }
        )
    return json.dumps(values)


def _fetch(runners: list[dict]) -> str:
    listing = json.dumps({"total_count": len(runners), "runners": runners})
    return f"""
        globalThis.fetch = async (url) => {{
          const body = url.includes("/access_tokens")
            ? {{ token: "installation-secret", expires_at: "2099-01-01T00:00:00Z" }} : {listing};
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
    """


def _driver(setup: str, parameters: str, runners: list[dict]) -> str:
    return f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        globalThis.__parameters = new Map(Object.entries({parameters}));
        globalThis.__scaled = null;
        globalThis.__terminated = null;
        globalThis.__activeInstances = true;
        {_environment("reaper")}
        {setup}
        {_fetch(runners)}
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
    """
