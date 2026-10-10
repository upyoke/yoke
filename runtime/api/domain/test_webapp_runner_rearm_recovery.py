"""Host replacement when a completed one-job registration never rearms."""

import shutil

import pytest

from runtime.api.domain.test_webapp_runner_github_broker import (
    _environment,
    _run_driver,
    _write_node_fixture,
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_stale_completed_runner_replaces_host_when_rearm_never_returns(
    tmp_path,
):
    _write_node_fixture(tmp_path)
    payload = _run_driver(
        tmp_path,
        f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        import {{ instantFromDate }} from "./webapp_runner_timestamps.mjs";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        const at = instantFromDate(new Date(Date.now() - 600000));
        globalThis.__parameters = new Map([
          ["/fleet/lifecycle-state", JSON.stringify({{
            idle_since: null, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "", idle_by_instance: {{}},
          }})],
          ["/fleet/queue-activity", "initial"],
          ["/fleet/runner-progress", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: null }})],
          ["/fleet/runner-completion", JSON.stringify({{
            action: "completed",
            runner_name: "yoke-github-actions-i-0123456789abcdef0",
            job_id: "456", at,
          }})],
          ["/fleet/bootstrap/i-0123456789abcdef0", JSON.stringify({{ state: "ready", at }})],
        ]);
        globalThis.__scaled = null;
        globalThis.__terminated = null;
        {_environment("reaper")}
        globalThis.fetch = async (url) => {{
          const body = url.includes("/access_tokens")
            ? {{ token: "installation-secret", expires_at: "2099-01-01T00:00:00Z" }}
            : {{ total_count: 0, runners: [] }};
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{ result, scaled: globalThis.__scaled,
          terminated: globalThis.__terminated }}));
    """,
    )

    assert payload["result"] == {
        "action": "replaced",
        "reason": "runner_rearm_failed",
    }
    assert payload["scaled"] is None
    assert payload["terminated"] == {
        "InstanceId": "i-0123456789abcdef0",
        "ShouldDecrementDesiredCapacity": False,
    }
