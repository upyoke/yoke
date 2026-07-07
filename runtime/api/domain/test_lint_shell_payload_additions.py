"""Late-scope regressions for shell-payload lint teaching.

Covers redirect-target glue, best-effort-write predicates,
``_DomainOnlyHit`` read-wrapping carve-outs, ``TAUGHT_ADAPTERS``
``read_shape`` fallback, and capture-first wrapper recognition for
read-shape adapters.
"""

from __future__ import annotations

from yoke_core.domain import lint_shell_quoted_function_payload as lint
from yoke_core.domain.lint_shell_quoted_function_payload_messages import (
    build_choreography_remediation,
)
from runtime.harness.hook_runner.types import Outcome


def _record(command: str) -> "lint.HookContext":
    return lint._build_context_from_payload({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
    })


CAPTURE_FIRST_TEMPLATE = (
    '_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX)\n'
    '{cmd} >"$_tmp" 2>&1; _rc=$?\n'
    'wc -l "$_tmp"; echo "---tail---"; '
    'tail -120 "$_tmp"; echo "---rc=$_rc---"'
)


def test_footer_does_not_recommend_nonexistent_function_call_cli() -> None:
    text = build_choreography_remediation(
        "yoke_core.cli.db_router qa run-add", "qa.run.record_verdict",
    )
    assert "function-call --stdin" not in text
    assert "function-call --payload" not in text
    assert "yoke_function_dispatch.dispatch(FunctionCallRequest" in text
    for seed in ("execute-structured-write", "sections upsert", "claim-work"):
        assert seed in text


def test_choreography_remediation_teaches_full_body_shape() -> None:
    """The denial message must teach the right shapes proactively:
    targeted ``--section`` reads, the exit-0 contract on missing
    sections, and the ``--output-file`` route for full bodies.
    """
    text = build_choreography_remediation(
        "yoke_core.cli.db_router items get", "items.get.run",
    )
    # Targeted-section pattern is named.
    assert "--section \"## File Budget\"" in text
    # Section absence is exit-0 — the message must explain it so
    # parallel-batch sibling cancellation is no longer a footgun.
    assert "stays empty" in text or "stdout empty" in text
    assert "parallel" in text
    # Full-body route names the renderer's --output-file path so
    # agents do not invent ``| head`` / ``| tail`` shapes for big bodies.
    assert "--output-file" in text
    assert "render_body" in text


def test_function_call_meta_cli_is_not_exempted() -> None:
    cmd = (
        "python3 -m yoke_core.api.service_client function-call --stdin "
        "| tee /tmp/function-call.json"
    )
    reason = lint.evaluate_command(cmd)
    assert reason is not None
    assert "No function id covers this exact subcommand path" in reason


def test_raw_status_update_emits_skill_orchestrated_note(monkeypatch) -> None:
    emitted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        lint,
        "_emit_denial",
        lambda _p, reason, *, outcome="denied": emitted.append((outcome, reason)),
    )
    decision = lint.evaluate(_record(
        "python3 -m yoke_core.cli.db_router items update YOK-1706 "
        "status reviewed-implementation"
    ))
    assert decision.outcome is Outcome.WARN
    assert decision.block is False
    assert "advance YOK-N <next>" in decision.message
    assert emitted and emitted[0][0] == "warn"


def test_ac1_redirect_target_glued_in_read_pipe() -> None:
    # Bug 1: 2>/dev/null | head -120 wrapping on a registered read-shape
    # adapter must pass — previously the splitter chopped /dev/null
    # away from its operator.
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router items get YOK-42 spec "
        "2>/dev/null | head -120"
    ) is None


def test_ac2_session_heartbeat_best_effort_wrapping_passes() -> None:
    # Bug 2: best-effort write predicate — /dev/null + || true.
    assert lint.evaluate_command(
        "python3 -m yoke_core.api.service_client session-heartbeat "
        ">/dev/null 2>&1 || true"
    ) is None


def test_ac3_session_checkpoint_best_effort_wrapping_passes() -> None:
    assert lint.evaluate_command(
        "python3 -m yoke_core.api.service_client session-checkpoint "
        "--step 1 --action charge --chainable true --item-id YOK-42 "
        "--status planned --required-path conduct "
        "--outcome pre-dispatch 2>/dev/null || true"
    ) is None


def test_ac4_flows_list_read_wrap_passes() -> None:
    # Bug 3: _DomainOnlyHit branch consults read-wrapping shape.
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router flows list "
        "--project yoke 2>/dev/null"
    ) is None


def test_ac5_query_read_wrap_passes() -> None:
    assert lint.evaluate_command(
        'python3 -m yoke_core.cli.db_router query '
        '"SELECT id FROM projects ORDER BY id" 2>/dev/null || true'
    ) is None


def test_ac6_deploy_defaults_read_wrap_passes() -> None:
    assert lint.evaluate_command(
        "yoke project-structure deploy-defaults get --project yoke || true"
    ) is None


def test_ac7_best_effort_does_not_cover_tee_then_rm() -> None:
    # Negative: substantive pipe consumer + follow-on rm must still deny.
    reason = lint.evaluate_command(
        "python3 -m yoke_core.api.service_client session-checkpoint "
        "--step 1 --action charge | tee /tmp/foo && rm /tmp/foo"
    )
    assert reason is not None


def test_best_effort_write_requires_noop_clause() -> None:
    reason = lint.evaluate_command(
        "python3 -m yoke_core.api.service_client session-checkpoint "
        "--step 1 --action charge 2>&1"
    )
    assert reason is not None


def test_ac8_hand_quoted_payload_still_denies() -> None:
    # Negative: the existing hand-quoted JSON payload deny path is untouched.
    reason = lint.evaluate_command(
        "printf '{\"a\":1}' | python3 -m yoke_core.api.service_client "
        "function-call --payload '{...}'"
    )
    assert reason is not None


def test_ac9_mutate_adapter_with_tee_still_denies() -> None:
    # Negative: the read-only wrapping carve-out does not loosen MUTATE
    # wrapping — items.scalar.update must still deny when wrapped.
    reason = lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router items update YOK-42 "
        "status 'reviewed-implementation' 2>&1 | tee /tmp/log"
    )
    assert reason is not None


def test_ac16_taught_read_shape_epic_task_get_body_passes() -> None:
    # Bug 8: TAUGHT_ADAPTERS read_shape fallback.
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router epic task-get-body "
        "1704 3 2>&1 | head -100"
    ) is None


def test_ac17_taught_read_shape_epic_review_get_passes() -> None:
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router epic review-get "
        "1704 3 2>&1 | tail -50"
    ) is None


def test_ac17b_progress_note_list_unsynced_passes() -> None:
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router epic "
        "progress-note-list-unsynced 1704 2>&1 | tail -20"
    ) is None


def test_ac17c_multi_pipe_read_chain_passes() -> None:
    # awk / sort / head are all in _READ_PIPE_VERBS.
    assert lint.evaluate_command(
        "python3 -m yoke_core.cli.db_router epic "
        "progress-note-list-unsynced 1704 | "
        "awk -F'|' '{print $3 \"|\" $4}' | "
        "sort -n -t'|' -k2 -r | head -5"
    ) is None


def test_ac17d_path_claim_list_taught_adapter_passes() -> None:
    # Bug 8 Half 2: path-claim-list added to TAUGHT_ADAPTERS read-shape.
    assert lint.evaluate_command(
        "python3 -m yoke_core.api.service_client path-claim-list "
        "--item YOK-42 2>&1 | head -60"
    ) is None


def test_ac17e_path_claim_get_taught_adapter_passes() -> None:
    assert lint.evaluate_command(
        "python3 -m yoke_core.api.service_client path-claim-get 5 2>&1"
    ) is None


def test_ac18_capture_first_wrapper_around_read_shape_passes() -> None:
    # Bug 9: mktemp-bound var + _rc=$? status capture + read tail clauses.
    cmd = CAPTURE_FIRST_TEMPLATE.format(
        cmd="python3 -m yoke_core.cli.db_router events list "
        "--item YOK-1704 --limit 400"
    )
    assert lint.evaluate_command(cmd) is None


def test_capture_first_wrapper_rejects_unsafe_mktemp_target() -> None:
    cmd = (
        '_tmp=$(mktemp -p /etc)\n'
        'python3 -m yoke_core.cli.db_router events list '
        '--item YOK-1704 >"$_tmp" 2>&1; _rc=$?\n'
        'tail -120 "$_tmp"'
    )
    assert lint.evaluate_command(cmd) is not None


def test_capture_first_wrapper_accepts_private_tmp_target() -> None:
    cmd = (
        '_tmp=$(mktemp /private/tmp/yoke-cmd.XXXXXX)\n'
        'python3 -m yoke_core.cli.db_router events list '
        '--item YOK-1704 >"$_tmp" 2>&1; _rc=$?\n'
        'tail -120 "$_tmp"'
    )
    assert lint.evaluate_command(cmd) is None


def test_ac19_capture_first_wrapper_around_taught_read_shape_passes() -> None:
    # Bug 8 + Bug 9 combined: capture-first wrapper around the taught
    # read-shape adapter (epic task-get-body).
    cmd = CAPTURE_FIRST_TEMPLATE.format(
        cmd="python3 -m yoke_core.cli.db_router epic task-get-body 1704 3"
    )
    assert lint.evaluate_command(cmd) is None


def test_ac20_capture_first_wrapper_around_mutate_still_denies() -> None:
    # Negative: the capture-first carve-out only fires for read-shape
    # adapters. items.scalar.update remains MUTATE.
    cmd = (
        '_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX)\n'
        'python3 -m yoke_core.cli.db_router items update YOK-42 '
        "status 'reviewed-implementation' "
        '>"$_tmp" 2>&1; _rc=$?'
    )
    assert lint.evaluate_command(cmd) is not None


# ---------------------------------------------------------------------------
# Statement-split fix: top-level newline / ``;`` ends the current
# statement's wrapping. Subsequent statements no longer falsely chain
# into "wrapping" of the registered adapter on the prior statement.
# ---------------------------------------------------------------------------


def test_statement_split_heartbeat_then_checkpoint_passes() -> None:
    # The combined multi-statement body the /yoke do skill USED
    # to emit (heartbeat best-effort wrapping + checkpoint statement +
    # echo, separated by unquoted newlines).
    cmd = (
        "python3 -m yoke_core.api.service_client session-heartbeat "
        ">/dev/null 2>&1 || true\n"
        "python3 -m yoke_core.api.service_client session-checkpoint "
        "--step 1 --action charge --chainable true --item-id YOK-42 "
        "--status planned --required-path conduct "
        "--outcome pre-dispatch 2>/dev/null || true\n"
        'echo "done"'
    )
    assert lint.evaluate_command(cmd) is None


def test_statement_split_multi_statement_read_body_passes() -> None:
    # Two independent db_router items get invocations on separate
    # lines plus a trailing echo. Each is a read-shape adapter; the
    # second statement's wrapping is NOT classified against the first.
    cmd = (
        "python3 -m yoke_core.cli.db_router items get YOK-42 body\n"
        "python3 -m yoke_core.cli.db_router items get YOK-42 status\n"
        'echo "done"'
    )
    assert lint.evaluate_command(cmd) is None


def test_statement_split_mutate_with_pipe_consumer_still_denies() -> None:
    # AC-5 (negative): the statement-split fix only ends wrapping at
    # statement separators (``\n`` / ``;``). A pipe consumer is a
    # compound-statement chain, NOT a new statement — MUTATE adapters
    # piped to substantive consumers still deny.
    cmd = (
        "python3 -m yoke_core.cli.db_router items update YOK-42 "
        "status 'reviewed-implementation' | tail -f /tmp/foo"
    )
    assert lint.evaluate_command(cmd) is not None


def test_statement_split_semicolon_keeps_choreography_deny() -> None:
    # ``;`` is intentionally NOT a statement separator in the wrapping
    # classifier: the existing choreography deny path on patterns like
    # ``; echo $?`` against registered MUTATE adapters must keep
    # firing. The newline-only statement-split fix only loosens the
    # multi-statement-`\n` shape — see AC-5.
    cmd = (
        "python3 -m yoke_core.cli.db_router projects has-capability "
        "yoke ephemeral-env; echo $?"
    )
    assert lint.evaluate_command(cmd) is not None
