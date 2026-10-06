"""Statement splitting in the shell-payload lint's wrapping classifier.

A top-level newline ends the current statement's wrapping, so a later
statement no longer chains into "wrapping" of the registered adapter on the
prior one. A pipe consumer and ``;`` stay inside the statement.
"""

from __future__ import annotations

from yoke_core.domain import lint_shell_quoted_function_payload as lint


def test_statement_split_heartbeat_then_checkpoint_passes() -> None:
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
    # Negative case: the statement-split fix only ends wrapping at
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
    # multi-statement-`\n` shape.
    cmd = (
        "python3 -m yoke_core.cli.db_router projects has-capability "
        "yoke ephemeral-env; echo $?"
    )
    assert lint.evaluate_command(cmd) is not None
