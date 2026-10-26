"""Combined Codex lifecycle and client output uses one confirmed envelope."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_cli.commands.adapters import hook_inprocess as client
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain import session_orientation as orientation
from yoke_core.domain import session_orientation_delivery as delivery
from yoke_core.hooks import codex_payload, local_entry, session_dispatch
from yoke_core.hooks.types import HookContext

pytestmark = pytest.mark.usefixtures("bound_project_context")


@pytest.fixture()
def lifecycle(monkeypatch, tmp_path, capsys):
    transcript = tmp_path / "rollout-session.jsonl"
    transcript.touch()
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_candidates",
        lambda _: [transcript],
    )
    root = tmp_path / "project"
    (root / ".yoke").mkdir(parents=True)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("YOKE_EXECUTOR", "codex")
    monkeypatch.setattr(delivery, "_composed_session", None)
    monkeypatch.setattr("yoke_harness.hooks.identity.detect_executor", lambda: "codex")
    monkeypatch.setattr(local_entry, "detect_executor", lambda: "codex")
    monkeypatch.setattr(client, "_touch_detached_resume", lambda: None)
    monkeypatch.setattr(client, "_active_local_universe", lambda: True)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection", lambda: None
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.command_workdir_stamp.stamp_command_workdir",
        lambda text, _: text,
    )
    for name in (
        "record_client_anchor",
        "ensure_machine_hooks_for_executor",
        "capture_codex_session",
        "record_model_facts_shipped",
        "settle_projection",
    ):
        monkeypatch.setattr(local_entry, name, lambda *a, **k: None)
    monkeypatch.setattr(
        local_entry, "stamp_hook_input", lambda p, text, *a: (text, None)
    )
    monkeypatch.setattr(local_entry, "relay_identity_payload", lambda *a, **k: {})
    monkeypatch.setattr(local_entry, "collect_client_facts", lambda *a, **k: {})
    monkeypatch.setattr(
        local_entry,
        "resolve_hook_project_scope",
        lambda _: SimpleNamespace(project_id=None),
    )
    monkeypatch.setattr(local_entry, "event_chain", lambda *a: [])
    monkeypatch.setattr(local_entry, "confirmed_served_model", lambda *a: None)
    monkeypatch.setattr(local_entry, "resolve_capability", lambda _: None)
    monkeypatch.setattr(session_dispatch, "_root_and_db", lambda _: (str(root), "db"))
    monkeypatch.setattr(session_dispatch, "_is_yoke_target", lambda *a: True)
    monkeypatch.setattr(session_dispatch, "_reap_stale_sessions", lambda *a: None)
    monkeypatch.setattr(
        "yoke_harness.hooks.session_lifecycle.sync_session_main_checkout",
        lambda *a: None,
    )
    monkeypatch.setattr(codex_payload, "resolve_session_id", lambda _: "session")
    facts = SessionModelFacts(requested_model="requested", model="served")
    monkeypatch.setattr(session_dispatch, "_codex_model_facts", lambda *a: facts)
    monkeypatch.setattr(
        "yoke_core.hooks.codex_model.resolve_entrypoint", lambda: "codex-cli"
    )
    register = Mock(return_value="")
    prompt = Mock()
    monkeypatch.setattr(session_dispatch, "_register_codex", register)
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.emit_harness_session_sent_first_user_prompt_submit",
        prompt,
    )
    monkeypatch.setattr(
        orientation, "_advisory_lines", lambda _: ["Install: yoke setup --agent"]
    )
    monkeypatch.setattr(orientation, "_git_line", lambda *a: "")
    monkeypatch.setattr(
        orientation, "_startup_block_lines", lambda: ["Use yoke help for commands."]
    )
    monkeypatch.setattr(
        "yoke_cli.config.setup_facts_summary.orientation_lines", lambda _: []
    )
    state = SimpleNamespace(
        root=root, register=register, prompt=prompt, fault="", facts=facts
    )

    def run(event, *, stdin_data, controls, **_):
        controls.final_outcome = "deny" if state.fault == "denied" else "allow"
        payload = json.loads(stdin_data)
        payload.update(controls.payload_extra)
        decision = session_dispatch.evaluate(
            HookContext(event, "codex", "codex-cli", payload)
        )
        if state.fault == "interrupted":
            raise KeyboardInterrupt()
        if state.fault == "denied":
            return '{"hookSpecificOutput":{"permissionDecision":"deny"}}', 0
        return decision.audit_fields.get("stdout", ""), 0

    monkeypatch.setattr(local_entry, "run_event", run)

    def invoke(event, **extra):
        payload = {"session_id": "session", "cwd": str(state.root), **extra}
        rc = client.evaluate_inprocess(
            event, json.dumps(payload), dry_run=False, cursor_invocation=False
        )
        assert rc == 0
        captured = capsys.readouterr()
        state.stderr = captured.err
        out = captured.out
        if not out:
            return ""
        envelope = json.loads(
            out
        )  # A raw prefix or two concatenated envelopes fails here.
        body = envelope.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert len(body.encode()) <= INLINE_CONTEXT_BYTES["codex"]
        return body

    state.invoke = invoke
    return state


def assert_emitted_marker(body):
    encoded = body.encode()
    assert json.loads(delivery._delivered_marker("session").read_text()) == {
        "byte_count": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


@pytest.mark.parametrize("source", ["startup", "resume", "fork", "clear", "compact"])
def test_early_delivery_suppresses_prompt_orientation_but_keeps_lifecycle(
    lifecycle, source
):
    body = lifecycle.invoke("SessionStart", source=source, transcript_path="transcript")
    assert body.count(orientation.ORIENTATION_HEADING) == 1
    assert_emitted_marker(body)
    assert lifecycle.invoke("UserPromptSubmit") == ""
    assert lifecycle.invoke("UserPromptSubmit") == ""
    assert lifecycle.register.call_count == 2
    assert lifecycle.register.call_args.args[2] == lifecycle.facts
    lifecycle.prompt.assert_called_once_with("", "session")
    assert codex_payload.read_runtime_cache_field("session", "source") == source


@pytest.mark.parametrize("miss", ["missing", "suppressed", "denied", "interrupted"])
@pytest.mark.parametrize("projectless", [False, True])
def test_missed_startup_recovers_once_on_prompt(lifecycle, miss, projectless):
    if projectless:
        lifecycle.root = lifecycle.root.parent / "outside"
        lifecycle.root.mkdir()
    if miss == "suppressed":
        assert lifecycle.invoke("SessionStart", source="startup") == ""
    elif miss in ("denied", "interrupted"):
        lifecycle.fault = miss
        if miss == "interrupted":
            with pytest.raises(KeyboardInterrupt):
                lifecycle.invoke("SessionStart", source="resume")
        else:
            assert lifecycle.invoke("SessionStart", source="resume") == ""
        lifecycle.fault = ""
    assert not delivery.orientation_delivered("session")
    body = lifecycle.invoke("UserPromptSubmit", source="startup")
    assert body.count(orientation.ORIENTATION_HEADING) == 1
    assert ("outside every Yoke project" in body) == projectless
    assert_emitted_marker(body)
    assert lifecycle.invoke("UserPromptSubmit") == ""
    lifecycle.prompt.assert_called_once_with("", "session")
    assert lifecycle.register.call_count >= 1


def test_registration_failure_keeps_recovery_in_one_budgeted_envelope(lifecycle):
    lifecycle.register.return_value = "registration_unavailable: repair the connection"
    body = lifecycle.invoke("SessionStart", source="resume")
    assert "registration_unavailable" in body
    assert "yoke sessions identity --json" in body
    assert body.count(orientation.ORIENTATION_HEADING) == 1
    assert_emitted_marker(body)
    prompt = lifecycle.invoke("UserPromptSubmit")
    assert "registration_unavailable" in prompt
    assert orientation.ORIENTATION_HEADING not in prompt
    lifecycle.prompt.assert_called_once()


@pytest.mark.parametrize("fault", ["denied", "interrupted"])
def test_first_prompt_emission_failure_retries_without_repeating_lifecycle(
    lifecycle, fault
):
    lifecycle.fault = fault
    if fault == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            lifecycle.invoke("UserPromptSubmit")
    else:
        assert lifecycle.invoke("UserPromptSubmit") == ""
    assert not delivery.orientation_delivered("session")
    lifecycle.fault = ""
    body = lifecycle.invoke("UserPromptSubmit")
    assert orientation.ORIENTATION_HEADING in body
    assert_emitted_marker(body)
    assert lifecycle.invoke("UserPromptSubmit") == ""
    lifecycle.register.assert_called_once()
    lifecycle.prompt.assert_called_once()


@pytest.mark.parametrize("fault", ["nonzero", "deny-envelope", "malformed"])
def test_invalid_or_denied_emission_never_confirms(
    lifecycle, monkeypatch, capsys, fault
):
    from yoke_harness.hooks.decision_render import render_context_stdout

    body = orientation.orientation_for_hook(
        "UserPromptSubmit",
        json.dumps({"session_id": "session", "cwd": str(lifecycle.root)}),
    )
    wire = render_context_stdout(body, "UserPromptSubmit")
    if fault == "deny-envelope":
        envelope = json.loads(wire)
        envelope["hookSpecificOutput"]["permissionDecision"] = "deny"
        wire = json.dumps(envelope)
    elif fault == "malformed":
        wire = "legacy raw prefix" + wire

    def emit():
        print(wire)
        return 2 if fault == "nonzero" else 0

    client._evaluate_confirming_orientation(emit)
    capsys.readouterr()
    assert not delivery.orientation_delivered("session")
    retry = lifecycle.invoke("UserPromptSubmit")
    assert_emitted_marker(retry)


def test_marker_write_failure_teaches_repair_and_allows_retry(lifecycle, monkeypatch):
    marker = delivery._delivered_marker("session")
    write_text = type(marker).write_text

    def fail_marker_write(path, *args, **kwargs):
        if path == marker:
            raise PermissionError("write access denied")
        return write_text(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(type(marker), "write_text", fail_marker_write)
        body = lifecycle.invoke("SessionStart", source="resume")
    assert orientation.ORIENTATION_HEADING in body
    assert "orientation_delivery_marker_unwritable" in lifecycle.stderr
    assert "YOKE_SCRATCH_ROOT" in lifecycle.stderr
    assert not delivery.orientation_delivered("session")
    retry = lifecycle.invoke("UserPromptSubmit")
    assert_emitted_marker(retry)


def test_registration_error_alone_stays_within_shared_budget(lifecycle):
    lifecycle.invoke("SessionStart", source="resume")
    lifecycle.register.return_value = "registration_unavailable: " + "長" * 5000
    body = lifecycle.invoke("UserPromptSubmit")
    assert "registration_unavailable" in body
    assert "yoke sessions identity --json" in body
    assert "full reason in hook stderr" in body
    assert lifecycle.register.return_value in lifecycle.stderr
    assert orientation.ORIENTATION_HEADING not in body


@pytest.mark.parametrize("source", ["clear", "compact"])
@pytest.mark.parametrize("fault", ["", "denied", "interrupted"])
def test_context_reset_reorients_existing_session_and_retries_lost_delivery(
    lifecycle, source, fault
):
    assert lifecycle.invoke(
        "SessionStart", source="startup", transcript_path="transcript"
    )
    lifecycle.fault = fault
    if fault == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            lifecycle.invoke("SessionStart", source=source)
    else:
        body = lifecycle.invoke("SessionStart", source=source)
        assert bool(body) == (not fault)
    lifecycle.fault = ""
    if fault:
        assert not delivery.orientation_delivered("session")
        assert lifecycle.invoke("UserPromptSubmit")
    assert delivery.orientation_delivered("session")
    assert lifecycle.invoke("UserPromptSubmit") == ""
    assert {call.args[1] for call in lifecycle.register.call_args_list} == {"session"}
