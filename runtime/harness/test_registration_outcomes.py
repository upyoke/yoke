"""Registration persists prompts independently of client orientation state."""

from unittest.mock import Mock, patch

import pytest

from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.hooks.registration_in_process import _register_in_process
from yoke_core.hooks.hook_registration_tail import apply_hook_session_tail
from yoke_core.hooks.run_tail import record_registration_outcome
from yoke_core.hooks.remote_policy import RunControls
from yoke_contracts.hook_runner.failures import render_failure_warning


@pytest.mark.parametrize(
    "code", ["SESSION_INSERT_REFUSED", "ACTOR_REQUIRED", "SESSION_ORG_UNRESOLVED"]
)
def test_refusal_reports_code_after_rollback(code):
    conn = Mock()
    actions = []
    conn.rollback.side_effect = lambda: actions.append("rollback")
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        patch(
            "yoke_core.hooks.registration_in_process.project_level_for_session",
            return_value=None,
        ),
        patch(
            "yoke_core.domain.sessions_lifecycle_registry.register_session",
            side_effect=SessionError(code, "repair cause"),
        ),
        patch(
            "yoke_core.hooks.registration_in_process.emit_registration_refused",
            side_effect=lambda *a, **k: actions.append("event"),
        ) as emit,
    ):
        outcome = _register_in_process(
            "session", "codex", "openai", SessionModelFacts(), "/project", None
        )
    assert outcome == f"refused:{code}"
    assert actions == ["rollback", "event"]
    assert emit.call_args.args[1] == code
    controls = RunControls()
    record_registration_outcome(controls, outcome)
    assert f"session_registration_refused:{code}" in render_failure_warning(
        controls.degraded
    )
    assert controls.final_outcome == ""


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_tail_forwards_prompt_even_when_orientation_marker_was_consumed(executor):
    conn = Mock()
    # No orientation marker is consulted by the authoritative write.
    with (
        patch(
            "yoke_core.hooks.registration.ensure_registered_from_hook",
            return_value="exists",
        ) as register,
        patch(
            "yoke_core.domain.session_presentation_observation.record_session_presentation"
        ),
    ):
        outcome = apply_hook_session_tail(
            conn,
            ensure_session=(
                "session",
                "{}",
                "",
                False,
                executor,
                True,
                True,
                1,
                1,
                True,
            ),
            observed_session=None,
        )
    assert outcome == "exists"
    assert register.call_args.kwargs["first_user_prompt"] is True


@pytest.mark.parametrize("outcome", ["registered", "exists", "skipped:relay_owned", "refused:ACTOR_REQUIRED"])
def test_cursor_orientation_reports_only_registration_refusals(monkeypatch, outcome):
    from yoke_core.hooks.session_dispatch_cursor import _render_orientation
    from yoke_core.hooks.types import HookContext
    from yoke_core.domain.session_orientation import CLIENT_ORIENTATION_PRESENT_KEY
    monkeypatch.setattr("yoke_core.hooks.session_dispatch_orientation._connected_env_remediation", lambda _: None)
    context = HookContext("SessionStart", "cursor", "cursor", {CLIENT_ORIENTATION_PRESENT_KEY: True})
    text = _render_orientation(context, "/project", outcome)
    if outcome.startswith("refused:"):
        assert outcome in text
        assert "repair the named cause" in text
    else:
        assert text == ""


def test_local_prompt_registration_uses_resolved_project_scope(monkeypatch):
    import json
    from types import SimpleNamespace
    from yoke_core.hooks import runner, run_tail, telemetry
    from yoke_core.hooks.adapter_capability import AdapterCapability
    from yoke_core.hooks.decision_render import render_claude_decision
    monkeypatch.setattr("yoke_contracts.hook_runner.project_scope.resolve_hook_project_scope", lambda _: SimpleNamespace(require_project_id=lambda: 7))
    monkeypatch.setattr("yoke_contracts.hook_runner.guard_scope.applicable_chain", lambda *a: [])
    monkeypatch.setattr(runner, "deduplicated_dispatch", lambda *a, **k: False)
    monkeypatch.setattr(run_tail, "flush_run_tail", lambda **k: None)
    requests = []
    monkeypatch.setattr(telemetry, "flush_hook_telemetry", lambda *a, **k: requests.append(k["ensure_session"]) or "registered")
    controls = RunControls()
    _text, code = runner.run_event("UserPromptSubmit", capability=AdapterCapability(
        family="claude", payload_parser=json.loads, decision_renderer=render_claude_decision,
    ), stdin_data=json.dumps({"session_id": "local-session", "cwd": "/project"}), controls=controls)
    assert code == 0
    assert requests[0][8] == 7
    assert requests[0][9] is True
    assert controls.registration_outcome == "registered"
