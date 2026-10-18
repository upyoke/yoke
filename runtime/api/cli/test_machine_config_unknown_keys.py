"""Extra machine settings must not take commands or hooks offline."""

import json
import sys

import pytest

from yoke_cli import command_router
from yoke_cli.config import machine_config as client
from yoke_contracts.machine_config import runtime, schema


def _config(tmp_path):
    payload = schema.canonical_example_payload()
    payload["future_root"] = {"ignored": True}
    payload["projects"][0]["future_project"] = "ignored"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload))
    return path, payload


def test_unknown_keys_warn_once_across_cli_and_hook_readers(
    tmp_path, monkeypatch, capsys
):
    config, payload = _config(tmp_path)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    for reader in (client, runtime, client, runtime):
        assert reader.load_config() == payload
    warnings = capsys.readouterr().err
    for key in ("future_root", "projects[0].future_project"):
        assert warnings.count(f"unknown key '{key}'") == 1
    assert str(config) in warnings
    assert "ignored" in warnings
    assert command_router._machine_config_ready(None) == (True, "")
    issues = schema.validate_payload(payload)
    assert {issue.severity for issue in issues} == {"warning"}
    assert {issue.path for issue in issues} == {
        "future_root",
        "projects[0].future_project",
    }


@pytest.mark.parametrize("value", [None, "invalid", -1, True])
def test_known_project_values_still_refuse(tmp_path, monkeypatch, value):
    config, payload = _config(tmp_path)
    payload["projects"][0]["project_id"] = value
    config.write_text(json.dumps(payload))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    ready, reason = command_router._machine_config_ready(None)
    assert not ready
    assert "positive integer project_id" in reason


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_hook_evaluation_survives_unknown_project_key(tmp_path, monkeypatch, executor):
    import io
    from runtime.api.cli.test_yoke_operations_cli_hooks import _FakeResponse
    from yoke_cli.main import main
    from yoke_harness.hooks import relay, machine_hooks

    config, payload = _config(tmp_path)
    token = tmp_path / "fixture.token"
    token.write_text("fixture-token")
    payload["connections"]["prod"]["api_url"] = "https://env.example"
    payload["connections"]["prod"]["credential_source"]["path"] = str(token)
    config.write_text(json.dumps(payload))
    original = config.read_bytes()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setenv("YOKE_ENV", "prod")
    monkeypatch.setattr(relay, "detect_executor", lambda: executor)
    monkeypatch.setattr(
        machine_hooks,
        "ensure_machine_hooks_for_executor",
        lambda _executor, **_kwargs: None,
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "cwd": str(tmp_path),
                    "tool_name": "Read",
                    "tool_input": {"file_path": str(tmp_path / "example.txt")},
                }
            )
        ),
    )
    requests = []

    def answer(request, **kwargs):
        requests.append(request)
        return _FakeResponse(
            b'{"hook_schema":1,"stdout":"","exit_code":0,'
            b'"wait_ms":1,"degraded":[],"outcome":"completed"}'
        )

    monkeypatch.setattr("urllib.request.urlopen", answer)
    assert main(["hook", "evaluate", "PreToolUse"]) == 0
    assert len(requests) == 1
    assert requests[0].full_url == "https://env.example/v1/hooks/evaluate"
    assert config.read_bytes() == original
