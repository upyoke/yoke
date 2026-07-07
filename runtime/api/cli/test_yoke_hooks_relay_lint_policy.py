"""Hook relay lint-policy snapshot tests."""

from __future__ import annotations

import io
import json
import sys

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    cli_main,
    https_connection,
    local_subset,
)
from yoke_contracts.hook_runner import lint_policy


def test_hook_evaluate_https_posts_client_lint_config_snapshot(
    monkeypatch, capsys, https_connection, local_subset,
) -> None:
    raw_stdin = '{"tool_name": "Bash"}'
    snapshot = {"lint_db_cmd_remote_claude_cli": {"mode": "warn"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_stdin))
    monkeypatch.setattr(
        "yoke_harness.hooks.relay._client_lint_config_snapshot",
        lambda _payload: snapshot,
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({
            "hook_schema": 1,
            "stdout": "",
            "exit_code": 0,
            "wait_ms": 1,
            "degraded": [],
            "outcome": "completed",
        }).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rc = cli_main(["hook", "evaluate", "PreToolUse"])

    assert rc == 0
    assert capsys.readouterr().out == ""
    posted_snapshot = captured["body"]["payload_extra"][
        lint_policy.SNAPSHOT_PAYLOAD_KEY
    ]
    assert posted_snapshot == snapshot
