"""Failure injection for durable runner-host termination recovery."""

from __future__ import annotations

import json
import shutil
import time

import pytest

from runtime.api.domain.test_webapp_runner_github_broker import (
    _environment,
    _run_driver,
    _write_node_fixture,
)
from runtime.api.domain.test_webapp_runner_lifecycle import (
    INSTANCE_ID,
    RUNNER_NAME,
    _parameters,
)


MARKER_NAME = f"/fleet/bootstrap/{INSTANCE_ID}"


def _driver(parameters: str, setup: str) -> str:
    return f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        globalThis.__parameters = new Map(Object.entries({parameters}));
        globalThis.__activeInstances = true;
        globalThis.__runnerPresent = true;
        globalThis.__terminationCalls = [];
        globalThis.__scaled = null;
        {_environment("reaper")}
        {setup}
        globalThis.fetch = async (url, options = {{}}) => {{
          let status = 200;
          let body = {{}};
          if (url.includes("/access_tokens")) {{
            body = {{ token: "installation-secret", expires_at: "2099-01-01T00:00:00Z" }};
          }} else if (url.includes("/actions/runners?")) {{
            const runners = globalThis.__runnerPresent ? [{json.dumps({
                "id": 101,
                "name": RUNNER_NAME,
                "status": "online",
                "busy": False,
                "labels": [
                    {"name": "self-hosted"}, {"name": "Linux"},
                    {"name": "X64"}, {"name": "yoke-github-actions"},
                ],
            })}] : [];
            body = {{ total_count: runners.length, runners }};
          }} else if (options.method === "DELETE") {{
            globalThis.__deleteAttempts = (globalThis.__deleteAttempts || 0) + 1;
            if (globalThis.__failRunnerDeleteOnce) {{
              globalThis.__failRunnerDeleteOnce = false;
              status = 500;
              body = {{ message: "runner deletion failed" }};
            }} else {{
              globalThis.__runnerPresent = false;
              status = 204;
            }}
          }}
          return {{ ok: status < 400, status,
            async text() {{ return status === 204 ? "" : JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
    """


def _idle_parameters() -> str:
    return _parameters(
        idle_since=int(time.time()) - 3600,
        online_instance_id=INSTANCE_ID,
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    ("setup", "expected_error", "expected_reason", "scale_mutations", "deletes"),
    [
        (
            "globalThis.__failQueueReadAfterTerminationOnce = true;",
            "queue read failed after termination", "idle", 0, 1,
        ),
        (
            'globalThis.__activityOnTerminate = "queued-race";\n'
            'globalThis.__restoreErrorOnce = "capacity restore failed";',
            "capacity restore failed", "queue_activity_race", 1, 1,
        ),
        (
            "globalThis.__failRunnerDeleteOnce = true;",
            "runner deletion failed", "idle", 0, 2,
        ),
        (
            "globalThis.__failLifecycleWriteAfterTerminationOnce = true;",
            "lifecycle write failed after termination", "idle", 0, 1,
        ),
        (
            'globalThis.__activityOnTerminate = "queued-race";\n'
            "globalThis.__failLifecycleWriteAfterTerminationOnce = true;",
            "lifecycle write failed after termination",
            "queue_activity_race", 1, 1,
        ),
    ],
)
def test_post_termination_failures_resume_without_reterminating(
    tmp_path,
    setup,
    expected_error,
    expected_reason,
    scale_mutations,
    deletes,
):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, _driver(_idle_parameters(), setup) + f"""
        let firstError = "";
        try {{ await handler({{ action: "reap" }}); }}
        catch (error) {{ firstError = error.message; }}
        const firstMarker = JSON.parse(globalThis.__parameters.get("{MARKER_NAME}"));
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{
          firstError, firstMarker, result,
          terminationCalls: globalThis.__terminationCalls.length,
          scaleMutations: globalThis.__scaleMutations || 0,
          deleteAttempts: globalThis.__deleteAttempts || 0,
          markerRemaining: globalThis.__parameters.has("{MARKER_NAME}"),
          lifecycle: JSON.parse(globalThis.__parameters.get("/fleet/lifecycle-state")),
        }}));
    """)

    assert expected_error in payload["firstError"]
    assert payload["firstMarker"]["state"] == "termination_acknowledged"
    assert payload["firstMarker"]["termination_attempts"] == 1
    assert payload["result"]["reason"] == expected_reason
    assert payload["terminationCalls"] == 1
    assert payload["scaleMutations"] == scale_mutations
    assert payload["deleteAttempts"] == deletes
    assert payload["markerRemaining"] is False
    assert payload["lifecycle"]["online_instance_id"] == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_ack_write_failure_recovers_from_requested_marker(tmp_path):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, _driver(
        _idle_parameters(),
        "globalThis.__failTerminationAckWriteOnce = true;",
    ) + f"""
        let firstError = "";
        try {{ await handler({{ action: "reap" }}); }}
        catch (error) {{ firstError = error.message; }}
        const firstMarker = JSON.parse(globalThis.__parameters.get("{MARKER_NAME}"));
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{
          firstError, firstMarker, result,
          terminationCalls: globalThis.__terminationCalls.length,
          markerRemaining: globalThis.__parameters.has("{MARKER_NAME}"),
        }}));
    """)

    assert payload["firstError"] == "termination acknowledgement write failed"
    assert payload["firstMarker"]["state"] == "termination_requested"
    assert payload["result"] == {"action": "scaled_down", "reason": "idle"}
    assert payload["terminationCalls"] == 1
    assert payload["markerRemaining"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_termination_api_retries_are_persisted_and_bounded(tmp_path):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, _driver(
        _idle_parameters(),
        'globalThis.__terminationError = "resource contention";',
    ) + f"""
        const errors = [];
        for (let attempt = 0; attempt < 4; attempt += 1) {{
          try {{ await handler({{ action: "reap" }}); }}
          catch (error) {{ errors.push(error.message); }}
        }}
        const marker = JSON.parse(globalThis.__parameters.get("{MARKER_NAME}"));
        console.log(JSON.stringify({{
          errors, marker,
          terminationAttempts: globalThis.__terminationAttempts || 0,
          runnerPresent: globalThis.__runnerPresent,
        }}));
    """)

    assert payload["errors"] == [
        "resource contention",
        "resource contention",
        "resource contention",
        "runner termination retry budget exhausted",
    ]
    assert payload["marker"]["state"] == "termination_requested"
    assert payload["marker"]["termination_attempts"] == 3
    assert payload["terminationAttempts"] == 3
    assert payload["runnerPresent"] is True
