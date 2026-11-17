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
