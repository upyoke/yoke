"""Failure-injection tests for the ephemeral runner lifecycle state machine."""

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


INSTANCE_ID = "i-0123456789abcdef0"
RUNNER_NAME = f"yoke-github-actions-{INSTANCE_ID}"


def _parameters(
    *,
    idle_since: int = 0,
    failures: int = 0,
    online_instance_id: str = "",
    queue_activity: str = "initial",
    marker_state: str | None = "ready",
    progress_event: dict | None = None,
    completion_event: dict | None = None,
) -> str:
    values = {
        "/fleet/lifecycle-state": json.dumps({
            "idle_since": idle_since,
            "queue_activity": "initial",
            "bootstrap_failures": failures,
            "online_instance_id": online_instance_id,
        }),
        "/fleet/queue-activity": queue_activity,
        "/fleet/runner-progress": json.dumps(progress_event or {
            "action": "none", "runner_name": "", "job_id": "", "at": 0,
        }),
        "/fleet/runner-completion": json.dumps(completion_event or {
            "action": "none", "runner_name": "", "job_id": "", "at": 0,
        }),
    }
    if marker_state is not None:
        values[f"/fleet/bootstrap/{INSTANCE_ID}"] = json.dumps({
            "state": marker_state,
            "at": int(time.time()) - 600,
        })
    return json.dumps(values)


def _fetch(runners: list[dict]) -> str:
    listing = json.dumps({"total_count": len(runners), "runners": runners})
    return f"""
        globalThis.fetch = async (url) => {{
          const body = url.includes("/access_tokens")
            ? {{ token: "installation-secret" }} : {listing};
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


def _online_runner(*, busy: bool = False) -> dict:
    return {
        "id": 101,
        "name": RUNNER_NAME,
        "status": "online",
        "busy": busy,
        "labels": [
            {"name": "self-hosted"}, {"name": "Linux"},
            {"name": "X64"}, {"name": "yoke-github-actions"},
        ],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_queue_activity_during_scale_down_restores_capacity(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(
        idle_since=int(time.time()) - 3600,
        online_instance_id=INSTANCE_ID,
    )
    payload = _run_driver(tmp_path, _driver(
        'globalThis.__activityOnTerminate = "queued-race";',
        parameters,
        [_online_runner()],
    ) + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, scaled: globalThis.__scaled, terminated: globalThis.__terminated,
          lifecycle: JSON.parse(globalThis.__parameters.get(
            "/fleet/lifecycle-state")),
        }));
    """)

    assert payload["result"] == {
        "action": "replaced", "reason": "queue_activity_race",
    }
    assert payload["scaled"]["DesiredCapacity"] == 1
    assert payload["terminated"]["ShouldDecrementDesiredCapacity"] is True
    assert payload["lifecycle"]["queue_activity"] == "queued-race"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_no_instance_reconciles_unacknowledged_queue_activity(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(queue_activity="queued-after-failure", marker_state=None)
    payload = _run_driver(tmp_path, _driver(
        "globalThis.__activeInstances = false;",
        parameters,
        [],
    ) + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, scaled: globalThis.__scaled,
          lifecycle: JSON.parse(globalThis.__parameters.get(
            "/fleet/lifecycle-state")),
        }));
    """)

    assert payload["result"] == {
        "action": "replaced", "reason": "queue_activity_reconciled",
    }
    assert payload["scaled"]["DesiredCapacity"] == 1
    assert payload["lifecycle"]["queue_activity"] == "queued-after-failure"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_failed_termination_does_not_consume_bootstrap_retry(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(failures=2, marker_state="failed")
    payload = _run_driver(tmp_path, _driver(
        'globalThis.__terminationError = "resource contention";',
        parameters,
        [],
    ) + """
        let error = "";
        try { await handler({ action: "reap" }); }
        catch (caught) { error = caught.message; }
        console.log(JSON.stringify({
          error,
          lifecycle: JSON.parse(globalThis.__parameters.get(
            "/fleet/lifecycle-state")),
        }));
    """)

    assert payload["error"] == "resource contention"
    assert payload["lifecycle"]["bootstrap_failures"] == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_bootstrap_retry_budget_exhaustion_scales_down(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(failures=3, marker_state="failed")
    payload = _run_driver(tmp_path, _driver("", parameters, []) + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
          lifecycle: JSON.parse(globalThis.__parameters.get(
            "/fleet/lifecycle-state")),
        }));
    """)

    assert payload["result"] == {
        "action": "scaled_down", "reason": "bootstrap_retry_exhausted",
    }
    assert payload["terminated"]["ShouldDecrementDesiredCapacity"] is True
    assert payload["lifecycle"]["bootstrap_failures"] == 4


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_signed_in_progress_event_prevents_transient_offline_recycle(tmp_path):
    _write_node_fixture(tmp_path)
    parameters = _parameters(
        online_instance_id=INSTANCE_ID,
        progress_event={
            "action": "in_progress",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": int(time.time()),
        },
    )
    payload = _run_driver(tmp_path, _driver("", parameters, []) + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
        }));
    """)

    assert payload["result"] == {
        "action": "kept", "reason": "job_event_in_progress",
    }
    assert payload["terminated"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_completion_wins_over_delayed_in_progress_delivery(tmp_path):
    _write_node_fixture(tmp_path)
    now = int(time.time())
    parameters = _parameters(
        online_instance_id=INSTANCE_ID,
        progress_event={
            "action": "in_progress",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": now,
        },
        completion_event={
            "action": "completed",
            "runner_name": RUNNER_NAME,
            "job_id": "789",
            "at": now - 5,
        },
    )
    payload = _run_driver(tmp_path, _driver("", parameters, []) + """
        const result = await handler({ action: "reap" });
        console.log(JSON.stringify({
          result, terminated: globalThis.__terminated,
        }));
    """)

    assert payload["result"] == {
        "action": "replaced", "reason": "ephemeral_runner_finished",
    }
    assert payload["terminated"] == {
        "InstanceId": INSTANCE_ID,
        "ShouldDecrementDesiredCapacity": False,
    }
