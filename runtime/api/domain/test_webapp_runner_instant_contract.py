"""Canonical stored-clock refusals and complete writer pause admission."""

import hashlib
import hmac
import json
import sys
import types
from importlib.resources import files
import shutil

import pytest

from yoke_core.domain.github_actions_runner_fleet_capability import (
    RunnerFleetLifecycleSettings,
)
from runtime.api.domain.test_webapp_registry_stack import _Recorder
from runtime.api.domain.test_webapp_runner_github_broker import (
    _environment,
    _run_driver,
)
from runtime.api.domain.webapp_runner_broker_test_support import (
    _write_node_fixture,
)
from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack


@pytest.mark.parametrize(
    "paused,concurrencies", [(False, (5, 2, 1)), (True, (0, 0, 0))]
)
def test_pause_applies_to_every_writer_and_bundles_canonical_resources(
    monkeypatch, paused, concurrencies
):
    recorder, _ = _runner_stack(monkeypatch, lifecycle_writers_paused=paused)
    for name, concurrency in zip(
        ("runnerFleetWebhook", "runnerFleetGithubBroker", "runnerFleetGithubReaper"),
        concurrencies,
        strict=True,
    ):
        resource = recorder.single(name)
        assert resource.kwargs["reserved_concurrent_executions"] == concurrency
        assets = resource.kwargs["code"].kwargs["assets"]
        suffix = "py" if name == "runnerFleetWebhook" else "mjs"
        bundled = assets[f"webapp_runner_timestamps.{suffix}"].kwargs["text"]
        assert (
            bundled.encode()
            == files("yoke_contracts").joinpath(f"timestamps.{suffix}").read_bytes()
        )


def test_pause_authority_drift_refuses_before_resources(monkeypatch):
    recorder = _Recorder()
    with pytest.raises(RuntimeError, match="lifecycle_writers_paused"):
        _runner_stack(
            monkeypatch,
            lifecycle_writers_paused=True,
            authority_overrides={"lifecycle_writers_paused": False},
            recorder=recorder,
        )
    assert recorder.resources == []


@pytest.mark.parametrize("value", ["false", 0, None])
def test_pause_requires_a_boolean_before_resources(monkeypatch, value):
    recorder = _Recorder()
    with pytest.raises(ValueError, match="runner_writer_pause_invalid"):
        _runner_stack(monkeypatch, lifecycle_writers_paused=value, recorder=recorder)
    assert recorder.resources == []
    with pytest.raises(ValueError, match="writers_paused"):
        RunnerFleetLifecycleSettings(writers_paused=value)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_clock_preserves_microseconds_and_epoch_before_1970(tmp_path):
    _write_node_fixture(tmp_path)
    payload = _run_driver(
        tmp_path,
        """
        import { canonicalInstant, compareInstants, elapsedSeconds } from './webapp_runner_clock.mjs';
        const first = '1969-12-31T23:59:59.999998Z';
        const second = '1969-12-31T23:59:59.999999Z';
        console.log(JSON.stringify({first: canonicalInstant(first),
          order: compareInstants(first, second), elapsed: elapsedSeconds(second, first)}));
    """,
    )
    assert payload == {
        "first": "1969-12-31T23:59:59.999998Z",
        "order": -1,
        "elapsed": 0.000001,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
@pytest.mark.parametrize(
    "value", [0, 1720000000, "2026-10-08T00:00:00Z", "2026-10-08T00:00:00.000000-00:00"]
)
def test_legacy_clock_refuses_before_state_write(tmp_path, value):
    _write_node_fixture(tmp_path)
    state = json.dumps(
        {
            "idle_since": value,
            "queue_activity": "initial",
            "bootstrap_failures": 0,
            "online_instance_id": "",
            "idle_by_instance": {},
        }
    )
    payload = _run_driver(
        tmp_path,
        _environment("reaper")
        + f"""
        globalThis.__parameters = new Map();
        const {{ writeLifecycleState }} = await import('./webapp_runner_aws_state.mjs');
        let error;
        try {{ await writeLifecycleState({state}); }} catch (caught) {{ error = caught.message; }}
        console.log(JSON.stringify({{error, writes: globalThis.__parameters.size}}));
    """,
    )
    assert payload["error"].startswith("runner_lifecycle_instant_invalid:")
    assert payload["writes"] == 0


@pytest.mark.parametrize("action", ["in_progress", "completed"])
def test_signed_webhook_asset_writes_canonical_event_clock(monkeypatch, action):
    recorder, _ = _runner_stack(monkeypatch)
    function = recorder.single("runnerFleetWebhook")
    assets = function.kwargs["code"].kwargs["assets"]
    timestamps = types.ModuleType("webapp_runner_timestamps")
    exec(
        compile(
            assets["webapp_runner_timestamps.py"].kwargs["text"],
            "timestamp_asset",
            "exec",
        ),
        timestamps.__dict__,
    )
    monkeypatch.setitem(sys.modules, "webapp_runner_timestamps", timestamps)
    writes = []
    ssm = types.SimpleNamespace(
        get_parameter=lambda **_: {"Parameter": {"Value": "secret"}},
        put_parameter=lambda **kwargs: writes.append(kwargs),
    )
    monkeypatch.setitem(
        sys.modules, "boto3", types.SimpleNamespace(client=lambda _: ssm)
    )
    for key, value in function.kwargs["environment"].kwargs["variables"].items():
        monkeypatch.setenv(key, str(value))
    namespace = {"__name__": "webhook_asset"}
    exec(compile(assets["index.py"].kwargs["text"], "webhook_asset", "exec"), namespace)
    body = json.dumps(
        {
            "repository": {"id": "789012", "full_name": "upyoke/yoke"},
            "action": action,
            "workflow_job": {
                "id": 123,
                "runner_name": "yoke-github-actions-i-0123456789abcdef0",
                "labels": ["self-hosted", "Linux", "ARM64", "yoke-github-actions"],
            },
        }
    )
    signature = hmac.new(b"secret", body.encode(), hashlib.sha256).hexdigest()
    response = namespace["handler"](
        {
            "body": body,
            "headers": {
                "X-Hub-Signature-256": "sha256=" + signature,
                "X-GitHub-Event": "workflow_job",
            },
        },
        None,
    )
    assert response["statusCode"] == 202 and len(writes) == 1
    event = json.loads(writes[0]["Value"])
    assert event["action"] == action and event["job_id"] == "123"
    value = event["at"]
    assert timestamps.format_instant(timestamps.parse_instant(value)) == value
    assert len(value) == 27 and value.endswith("Z")
