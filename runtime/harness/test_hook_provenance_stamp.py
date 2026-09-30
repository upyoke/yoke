"""Execution provenance line names client and optional server fingerprints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts import execution_provenance as provenance
from yoke_core.domain.execution_provenance import (
    PROVENANCE_KEYS,
    collect_execution_provenance,
    format_provenance_line,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_harness.hooks import relay
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


def test_collect_execution_provenance_has_required_keys() -> None:
    blob = collect_execution_provenance()
    assert tuple(blob) == PROVENANCE_KEYS
    assert blob["source_sha"]
    assert blob["install_kind"]
    assert blob["install_path"]


def test_format_provenance_line_client_and_server_and_fallback() -> None:
    client = {
        "source_sha": "aaa",
        "install_kind": "source_checkout",
        "install_path": "/client",
    }
    server = {
        "source_sha": "bbb",
        "install_kind": "installed_wheel",
        "install_path": "/server",
    }
    line = format_provenance_line(client, server, fallback_local=True)
    assert line.startswith("yoke-provenance ")
    assert "client sha=aaa" in line
    assert "server sha=bbb" in line
    assert "fallback=local" in line


def test_default_provenance_stays_bound_to_loaded_process(monkeypatch) -> None:
    loaded = collect_execution_provenance()
    monkeypatch.setattr(provenance, "_git_sha", lambda _root: "new-head")

    assert collect_execution_provenance() == loaded


def test_explicit_provenance_probe_uses_supplied_build_revision() -> None:
    probed = collect_execution_provenance(
        module_file=__file__,
        env={"YOKE_BUILD_SHA": "c" * 40},
    )

    assert probed["source_sha"] == "c" * 40


@pytest.mark.parametrize("path", ["local", "relay_local", "relay_server"])
@pytest.mark.parametrize("denied", [True, False])
def test_hook_provenance_is_printed_only_on_allow(path, denied, monkeypatch, capsys):
    reason = "BLOCKED: policy reason" if denied else ""
    monkeypatch.setattr(relay, "detect_executor", lambda: "claude-code")
    monkeypatch.setattr(relay, "_client_lint_config_snapshot", lambda _p: {})
    monkeypatch.setattr(relay, "stamp_hook_input", lambda *a: ("{}", None))
    monkeypatch.setattr(relay, "settle_projection", lambda *a: None)
    monkeypatch.setattr(
        "yoke_harness.hooks.cursor_lifecycle_hooks.ensure_user_lifecycle_hooks_for_executor",
        lambda _e: None,
    )
    local_denied = denied and path != "relay_server"
    monkeypatch.setattr(
        relay,
        "evaluate_local_subset",
        lambda *a, **k: LocalSubsetEvaluation(
            reason if local_denied else "", 2 if local_denied else 0, local_denied
        ),
    )
    monkeypatch.setattr(relay, "relay_denial_audit", lambda *a: None)
    monkeypatch.setattr(relay, "_codex_capture", lambda *a: None)
    monkeypatch.setattr(relay, "deny_unstamped_relay", lambda _p: None)
    monkeypatch.setattr(relay, "relay_identity_payload", lambda *a: {"project_id": 1})
    monkeypatch.setattr(relay, "record_model_facts_shipped", lambda *a: None)
    monkeypatch.setattr(
        relay,
        "request_json",
        lambda *a, **k: SimpleNamespace(
            payload={
                "stdout": reason,
                "exit_code": 2 if denied else 0,
                "outcome": "denied" if denied else "completed",
                "execution_provenance": collect_execution_provenance(),
            }
        ),
    )
    if path == "local":
        rc = relay.evaluate_hook_event("PreToolUse", stdin_data="{}")
    else:
        rc = relay.relay_hook_event(
            "PreToolUse",
            HttpsConnection(api_url="https://env.example", token="test"),
            stdin_data="{}",
        )
    output = capsys.readouterr()
    assert rc == (2 if denied else 0)
    assert output.out == ""
    if denied:
        assert output.err == f"{reason}\n"
    assert ("yoke-provenance" in output.err) is not denied
