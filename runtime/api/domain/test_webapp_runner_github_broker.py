"""Executable contracts for the isolated runner GitHub App Lambdas."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

from runtime.api.domain.webapp_runner_broker_test_support import (
    _write_node_fixture,
)

def _environment(mode: str) -> str:
    return textwrap.dedent(f"""
        Object.assign(process.env, {{
          BROKER_MODE: "{mode}",
          GITHUB_API_URL: "https://api.github.com",
          GITHUB_APP_ISSUER: "Iv1.runner",
          GITHUB_INSTALLATION_ID: "123456",
          GITHUB_REPOSITORY_ID: "789012",
          GITHUB_REPO_OWNER: "acme",
          GITHUB_REPO_NAME: "service",
          GITHUB_PRIVATE_KEY_SECRET_ARN:
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:app-AbCdEf",
          RUNNER_ASG_NAME: "runner-asg",
          RUNNER_ARCHITECTURE: "x64",
          RUNNER_PREFIX: "yoke-github-actions-",
          RUNNER_LABELS: "self-hosted,Linux,X64,yoke-github-actions",
          IDLE_MINUTES: "30",
          LIFECYCLE_STATE_PARAMETER: "/fleet/lifecycle-state",
          QUEUE_ACTIVITY_PARAMETER: "/fleet/queue-activity",
          RUNNER_PROGRESS_PARAMETER: "/fleet/runner-progress",
          RUNNER_COMPLETION_PARAMETER: "/fleet/runner-completion",
          BOOTSTRAP_MARKER_PREFIX: "/fleet/bootstrap",
          BOOTSTRAP_TIMEOUT_MINUTES: "30",
          READY_GRACE_MINUTES: "5",
          MAX_BOOTSTRAP_RETRIES: "3",
          JOB_EVENT_TIMEOUT_MINUTES: "360",
        }});
    """)


def _run_driver(tmp_path: Path, body: str) -> dict:
    driver = tmp_path / "driver.mjs"
    driver.write_text(textwrap.dedent(body))
    result = subprocess.run(
        ["node", str(driver)], cwd=tmp_path, text=True, check=True,
        capture_output=True,
    )
    assert "installation-secret" not in result.stdout
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_bootstrap_is_one_time_and_cannot_invoke_reaper(tmp_path):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        globalThis.__parameters = new Map([
          ["/fleet/lifecycle-state", JSON.stringify({{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
          }})],
          ["/fleet/queue-activity", "initial"],
          ["/fleet/runner-progress", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
          ["/fleet/runner-completion", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
        ]);
        {_environment("bootstrap")}
        const calls = [];
        globalThis.fetch = async (url, options = {{}}) => {{
          const tokenRequest = url.includes("/access_tokens");
          calls.push({{ url, body: options.body || "", redirect: options.redirect }});
          let body = {{}};
          if (tokenRequest) body = {{ token: "installation-secret" }};
          else if (url.endsWith("/registration-token")) {{
            body = {{ token: "registration-token" }};
          }} else if (url.endsWith("/actions/runners/downloads")) {{
            body = [{{ os: "linux", architecture: "x64",
              download_url: "https://github.example/runner.tar.gz" }}];
          }}
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
        const event = {{ action: "bootstrap", instance_id: "i-0123456789abcdef0" }};
        const bootstrap = await handler(event);
        let earlyRegister = "";
        try {{
          await handler({{
            action: "register", instance_id: "i-0123456789abcdef0",
          }});
        }} catch (error) {{ earlyRegister = error.message; }}
        const ready = await handler({{
          action: "ready", instance_id: "i-0123456789abcdef0",
        }});
        const register = await handler({{
          action: "register", instance_id: "i-0123456789abcdef0",
        }});
        let secondBootstrap = "";
        try {{ await handler(event); }} catch (error) {{ secondBootstrap = error.message; }}
        let reap = "";
        try {{ await handler({{ action: "reap" }}); }} catch (error) {{ reap = error.message; }}
        console.log(JSON.stringify({{ bootstrap, earlyRegister, ready, register,
          secondBootstrap, reap, calls,
          marker: JSON.parse(globalThis.__parameters.get(
            "/fleet/bootstrap/i-0123456789abcdef0")),
        }}));
    """)

    assert payload["bootstrap"] == {
        "download_url": "https://github.example/runner.tar.gz",
        "registration_token": "registration-token",
    }
    assert payload["ready"]["runner_name"] == (
        "yoke-github-actions-i-0123456789abcdef0"
    )
    assert payload["register"] == {
        "registration_token": "registration-token",
    }
    assert payload["earlyRegister"] == (
        "runner host is not ready for another registration"
    )
    assert payload["marker"]["state"] == "ready"
    assert "already consumed" in payload["secondBootstrap"]
    assert payload["reap"] == "unsupported runner broker action"
    assert all(call["redirect"] == "error" for call in payload["calls"])
    token_calls = [
        call for call in payload["calls"]
        if call["url"].endswith("/access_tokens")
    ]
    assert len(token_calls) == 3
    for call in token_calls:
        body = json.loads(call["body"])
        permissions = body["permissions"]
        assert permissions == {"administration": "write"}
        assert set(permissions).isdisjoint({
            "actions_variables", "repository_hooks",
        })
        assert body == {
            "repository_ids": [789012],
            "permissions": permissions,
        }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_reaper_paginates_before_keeping_a_busy_runner(tmp_path):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        const at = Math.floor(Date.now() / 1000) - 600;
        globalThis.__parameters = new Map([
          ["/fleet/lifecycle-state", JSON.stringify({{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "i-0123456789abcdef0",
          }})],
          ["/fleet/queue-activity", "initial"],
          ["/fleet/runner-progress", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
          ["/fleet/runner-completion", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
          ["/fleet/bootstrap/i-0123456789abcdef0", JSON.stringify({{ state: "ready", at }})],
        ]);
        globalThis.__scaled = null;
        {_environment("reaper")}
        const calls = [];
        globalThis.fetch = async (url, options = {{}}) => {{
          calls.push(url);
          const page = new URL(url).searchParams.get("page");
          let body = {{}};
          if (url.includes("/access_tokens")) body = {{ token: "installation-secret" }};
          else if (page === "1") body = {{
            total_count: 101,
            runners: Array.from({{ length: 100 }}, (_, index) => ({{
              id: index + 1, name: `unrelated-${{index}}`, status: "offline",
              busy: false, labels: [],
            }})),
          }};
          else if (page === "2") body = {{
            total_count: 101,
            runners: [{{
              id: 101, name: "yoke-github-actions-i-0123456789abcdef0",
              status: "online", busy: true,
              labels: ["self-hosted", "Linux", "X64", "yoke-github-actions"]
                .map((name) => ({{ name }})),
            }}],
          }};
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{ result, calls, scaled: globalThis.__scaled }}));
    """)

    assert payload["result"] == {"action": "kept", "reason": "busy"}
    assert payload["scaled"] is None
    runner_pages = [url for url in payload["calls"] if "actions/runners?" in url]
    assert len(runner_pages) == 2
    assert "page=1" in runner_pages[0]
    assert "page=2" in runner_pages[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is unavailable")
def test_stale_completed_runner_replaces_host_when_rearm_never_returns(
    tmp_path,
):
    _write_node_fixture(tmp_path)
    payload = _run_driver(tmp_path, f"""
        import {{ generateKeyPairSync }} from "node:crypto";
        globalThis.__privateKey = generateKeyPairSync("rsa", {{ modulusLength: 2048 }})
          .privateKey.export({{ type: "pkcs8", format: "pem" }});
        const at = Math.floor(Date.now() / 1000) - 600;
        globalThis.__parameters = new Map([
          ["/fleet/lifecycle-state", JSON.stringify({{
            idle_since: 0, queue_activity: "initial", bootstrap_failures: 0,
            online_instance_id: "",
          }})],
          ["/fleet/queue-activity", "initial"],
          ["/fleet/runner-progress", JSON.stringify({{
            action: "none", runner_name: "", job_id: "", at: 0 }})],
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
            ? {{ token: "installation-secret" }}
            : {{ total_count: 0, runners: [] }};
          return {{ ok: true, status: 200,
            async text() {{ return JSON.stringify(body); }} }};
        }};
        const {{ handler }} = await import("./webapp_runner_github_broker.mjs");
        const result = await handler({{ action: "reap" }});
        console.log(JSON.stringify({{ result, scaled: globalThis.__scaled,
          terminated: globalThis.__terminated }}));
    """)

    assert payload["result"] == {
        "action": "replaced",
        "reason": "runner_rearm_failed",
    }
    assert payload["scaled"] is None
    assert payload["terminated"] == {
        "InstanceId": "i-0123456789abcdef0",
        "ShouldDecrementDesiredCapacity": False,
    }
