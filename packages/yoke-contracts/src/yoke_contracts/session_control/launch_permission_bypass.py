"""How a relay-launched session disables interactive approval per harness.

A session the launch plane starts is an autonomous fleet worker: no operator
is watching its terminal, so an approval prompt is not a question, it is a
stall. Every launched session therefore runs with its harness's permission
bypass engaged, on both the create and the wake route.

Each harness expresses that posture differently, so the facts live here once
and every native transport reads them from this module rather than spelling a
vendor flag inline. The declarations are grounded against the native builds
this repository supports:

* ``claude-code`` — ``--dangerously-skip-permissions`` on the ``claude``
  invocation. The flag is inside the CLI's own persisted respawn-flag
  allowlist, so a background job keeps it when the wake route respawns it.
  ``--bg`` additionally refuses bypass until the disclaimer has been accepted
  once on the machine; :data:`CLAUDE_BYPASS_DISCLAIMER_RECOVERY` is the
  recovery step a refused launch reports.
* ``codex`` — the CLI exec route takes
  ``--dangerously-bypass-approvals-and-sandbox``; the app-server route has no
  such flag and carries the same posture as typed thread parameters instead
  (``approvalPolicy`` plus the sandbox mode, which ``turn/start`` spells as a
  tagged policy object).
* ``cursor`` — the CLI resume route takes ``--force`` (auto-approve commands)
  alongside the ``--trust`` it already passes. The ACP launch route has no
  flag to pass: ``cursor-agent acp`` accepts none, and the relay itself
  answers every ``session/request_permission`` and owns the terminals the
  agent runs commands in, so that route is already unattended by
  construction. :data:`CURSOR_ACP_BYPASS_IS_RELAY_ANSWERED` records that as a
  designed answer rather than a silent gap.

Interactive operator sessions are unaffected — nothing here is consulted
outside the relay's launch and wake transports.
"""

from __future__ import annotations

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS


CLAUDE_BYPASS_ARGUMENTS: tuple[str, ...] = ("--dangerously-skip-permissions",)
CLAUDE_BYPASS_DISCLAIMER_REFUSAL = "requires accepting the disclaimer"
CLAUDE_BYPASS_DISCLAIMER_RECOVERY = (
    "Claude Code refuses a background launch with bypassed permissions until "
    "the machine has accepted the bypass disclaimer once. Run "
    "`claude --dangerously-skip-permissions` interactively on this machine, "
    "accept the prompt, then retry the launch."
)

CODEX_EXEC_BYPASS_ARGUMENTS: tuple[str, ...] = (
    "--dangerously-bypass-approvals-and-sandbox",
)
CODEX_APPROVAL_POLICY = "never"
CODEX_SANDBOX_MODE = "danger-full-access"
CODEX_TURN_SANDBOX_POLICY: dict[str, str] = {"type": "dangerFullAccess"}

CURSOR_CLI_BYPASS_ARGUMENTS: tuple[str, ...] = ("--force",)
CURSOR_ACP_BYPASS_IS_RELAY_ANSWERED = True


_CLI_BYPASS_ARGUMENTS = {
    "claude-code": CLAUDE_BYPASS_ARGUMENTS,
    "codex": CODEX_EXEC_BYPASS_ARGUMENTS,
    "cursor": CURSOR_CLI_BYPASS_ARGUMENTS,
}

if tuple(sorted(_CLI_BYPASS_ARGUMENTS)) != tuple(sorted(CANONICAL_HARNESS_IDS)):
    raise RuntimeError("launch permission bypass must cover every harness family")


def cli_bypass_arguments(harness_id: str) -> tuple[str, ...]:
    """Return the command-line bypass arguments one harness family expects."""
    try:
        return _CLI_BYPASS_ARGUMENTS[harness_id]
    except KeyError as exc:
        raise ValueError(f"unknown harness id: {harness_id!r}") from exc


def codex_thread_bypass_parameters() -> dict[str, str]:
    """Return the app-server thread parameters that start a thread unattended."""
    return {"approvalPolicy": CODEX_APPROVAL_POLICY, "sandbox": CODEX_SANDBOX_MODE}


def codex_turn_bypass_parameters() -> dict[str, object]:
    """Return the same posture in the shape ``turn/start`` accepts."""
    return {
        "approvalPolicy": CODEX_APPROVAL_POLICY,
        "sandboxPolicy": dict(CODEX_TURN_SANDBOX_POLICY),
    }


__all__ = [
    "CLAUDE_BYPASS_ARGUMENTS",
    "CLAUDE_BYPASS_DISCLAIMER_RECOVERY",
    "CLAUDE_BYPASS_DISCLAIMER_REFUSAL",
    "CODEX_APPROVAL_POLICY",
    "CODEX_EXEC_BYPASS_ARGUMENTS",
    "CODEX_SANDBOX_MODE",
    "CODEX_TURN_SANDBOX_POLICY",
    "CURSOR_ACP_BYPASS_IS_RELAY_ANSWERED",
    "CURSOR_CLI_BYPASS_ARGUMENTS",
    "cli_bypass_arguments",
    "codex_thread_bypass_parameters",
    "codex_turn_bypass_parameters",
]
