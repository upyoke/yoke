"""Executable contract for per-host idle reaping in a parallel runner pool.

Sibling of ``test_webapp_runner_github_broker.py``; separate so neither file
approaches the authored-file line limit. Reuses that module's node driver and
environment helpers rather than restating them.
"""

from __future__ import annotations

import shutil

import pytest

from runtime.api.domain.test_webapp_runner_github_broker import (
    _environment,
    _run_driver,
)
from runtime.api.domain.webapp_runner_broker_test_support import (
    _write_node_fixture,
)

_BUSY = "i-0aaaaaaaaaaaaaaa1"
_IDLE = "i-0bbbbbbbbbbbbbbb2"


def _two_host_driver(
    lifecycle_state: str,
    *,
    idle_marker_age_seconds: int = 7200,
) -> str:
    """Drive one reap pass over a busy host and a long-idle host."""
    return f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        const ready = Math.floor(Date.now() / 1000) - 7200;
        const idleReady = Math.floor(Date.now() / 1000) - {idle_marker_age_seconds};
        globalThis.__activeInstances = ["{_BUSY}", "{_IDLE}"];
        globalThis.__parameters = new Map([
          ["/fleet/lifecycle-state", JSON.stringify({lifecycle_state})],
          ["/fleet/queue-activity", "initial"],
          ["/fleet/runner-progress", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
          ["/fleet/runner-completion", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
          ["/fleet/bootstrap/{_BUSY}", JSON.stringify({{ state: "ready", at: ready }})],
          ["/fleet/bootstrap/{_IDLE}", JSON.stringify({{
            state: "ready", at: idleReady }})],
        ]);
        globalThis.__scaled = null;
        globalThis.__terminated = null;
        {_environment("reaper")}
        globalThis.fetch = async (url) => {{
          const labels = ["self-hosted", "Linux", "X64", "yoke-github-actions"]
            .map((name) => ({{ name }}));
          const body = url.includes("/access_tokens")
            ? {{ token: "installation-secret", expires_at: "2099-01-01T00:00:00Z" }}
            : {{ total_count: 2, runners: [
                {{ id: 1, name: "yoke-github-actions-{_BUSY}",
                   status: "online", busy: true, labels }},
                {{ id: 2, name: "yoke-github-actions-{_IDLE}",
                   status: "online", busy: false, labels }},
              ] }};
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{ result, terminated: globalThis.__terminated,
          state: JSON.parse(globalThis.__parameters.get("/fleet/lifecycle-state")) }}));
    """


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_a_busy_host_no_longer_keeps_an_idle_host_alive(tmp_path):
    """A host idle past the window retires even while a sibling is busy.

    The pool previously shared one idle clock, so any busy host reset the timer
    for every other host and idle hosts outlived the window indefinitely.
    """
    _write_node_fixture(tmp_path)
    stale = "Math.floor(Date.now() / 1000) - 7200"
    payload = _run_driver(tmp_path, _two_host_driver(
        f"""{{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
            idle_by_instance: {{ "{_IDLE}": {stale} }},
        }}"""
    ))

    assert payload["result"] == {"action": "scaled_down", "reason": "idle"}
    assert payload["terminated"]["InstanceId"] == _IDLE
    assert payload["terminated"]["ShouldDecrementDesiredCapacity"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_a_freshly_idle_host_is_kept_and_starts_its_own_clock(tmp_path):
    """First idle pass records the host's own start time and keeps it."""
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, _two_host_driver(
        """{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
        }"""
    ))

    assert payload["result"] == {"action": "kept", "reason": "busy"}
    assert payload["terminated"] is None
    idle_by_instance = payload["state"]["idle_by_instance"]
    # The busy host carries no mark; the idle one starts its own clock.
    assert _BUSY not in idle_by_instance
    assert idle_by_instance[_IDLE] > 0


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_idle_clocks_survive_a_queue_activity_change(tmp_path):
    """A job event elsewhere must not restart every host's idle clock.

    Queue activity changes on every job event, and the state reset that follows
    used to rebuild the record from scratch. Dropping the marks there would
    restart the clocks many times an hour, so no host would ever reach the
    window — the same failure the per-host clocks exist to prevent.
    """
    _write_node_fixture(tmp_path)
    stale = "Math.floor(Date.now() / 1000) - 7200"
    driver = _two_host_driver(
        f"""{{
            idle_since: 0, queue_activity: "stale-activity", bootstrap_failures: 0,
            online_instance_id: "",
            idle_by_instance: {{ "{_IDLE}": {stale} }},
        }}"""
    )
    payload = _run_driver(tmp_path, driver)

    # "initial" in the queue-activity parameter differs from "stale-activity"
    # in the record, so the reap pass runs through the reset path.
    assert payload["result"] == {"action": "scaled_down", "reason": "idle"}
    assert payload["terminated"]["InstanceId"] == _IDLE


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_rearmed_host_cannot_inherit_pre_job_idle_time(tmp_path):
    """A fresh one-job registration resets only that host's idle window."""
    _write_node_fixture(tmp_path)
    stale = "Math.floor(Date.now() / 1000) - 7200"
    payload = _run_driver(tmp_path, _two_host_driver(
        f"""{{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
            idle_by_instance: {{ "{_IDLE}": {stale} }},
        }}""",
        idle_marker_age_seconds=2,
    ))

    assert payload["result"] == {"action": "kept", "reason": "busy"}
    assert payload["terminated"] is None
    assert payload["state"]["idle_by_instance"][_IDLE] > 0


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_a_host_that_went_busy_again_loses_its_idle_mark(tmp_path):
    """Claiming a job clears that host's clock without touching its siblings."""
    _write_node_fixture(tmp_path)
    stale = "Math.floor(Date.now() / 1000) - 7200"
    payload = _run_driver(tmp_path, _two_host_driver(
        f"""{{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
            idle_by_instance: {{ "{_BUSY}": {stale}, "{_IDLE}": {stale} }},
        }}"""
    ))

    # The busy host held a stale mark from an earlier idle spell; it must be
    # dropped rather than making a working host look reapable.
    assert payload["terminated"]["InstanceId"] == _IDLE
    assert _BUSY not in payload["state"]["idle_by_instance"]
