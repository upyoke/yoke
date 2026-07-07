"""Universal hook ordering — single-source policy chains per event type.

The renderer reads this module and emits each chain in
each harness's native config format (Claude ``settings.json`` /
Codex ``hooks.json``). Hook adapters carry only payload-shape translation
and decision rendering; this module is the source of truth for *which*
policies fire in *what* order.

Public surface:

- :data:`HOOK_ORDERING` — frozen mapping ``{event_type: {matcher: [module, ...]}}``.
- :func:`ordered_pipeline_for` — typed accessor returning a fresh ``list[str]``
  for ``(event_type, matcher)``. Returns an empty list when the pair is not
  registered (forward-compatible: harnesses may declare matchers we haven't
  pre-populated yet).

Module ids (the strings in each chain) are dotted Python module paths the
renderer uses verbatim as the ``python3 -m <module>`` payload. Modules
referenced here MUST exist by the time the renderer runs.

PreToolUse Bash chain order rationale:

1. ``lint_db_cmd`` — neutral DB-command guard; blocks raw ``sqlite3``
   invocations early (cheapest deny) while preserving the legacy stable
   ``lint-sqlite-cmd`` telemetry/check id.
2. ``lint_event_registry`` — block emission of unregistered events.
3. ``lint_main_commit`` — block ``git commit`` on main.
4. ``lint_tc_label`` — TC-label hygiene.
5. ``lint_long_command_polling`` — same-capture polling discipline.
5b. ``lint_pipe_to_truncator`` — block piping a live long command
   (watcher wrappers, pytest, run_tests, doctor/deploy engines) into
   ``tail``/``head``. Owns the pipe-to-truncator clause of the AGENTS.md
   Command Output rule: the truncator both discards failure context and
   masks the command's exit code. Pure shape parse; runs beside the
   polling lint because both protect long-command output discipline.
6. ``lint_subagent_background`` — subagent context deny for background
   watcher flows and wake-loss-prone tools. Runs right after the polling
   lint because the rules are architecturally adjacent (both protect
   long-command discipline); subagent context fails open by default so
   main sessions never see the deny path.
7. ``lint_session_cwd`` — broadest cwd-mismatch gate; runs first among
   the new entries because it scopes the rest.
8. ``lint_workspace_cwd_match`` — deny writer-class commands (pytest, the
   renderer CLI, run_tests) when ``$YOKE_BOUND_WORKSPACE`` is set and the
   cwd is outside that workspace. Runs after lint_session_cwd because both
   guards consult cwd; this one is verb-scoped (writer-class only) where
   lint_session_cwd is universal.
9. ``path_claim_bash_guard`` — claim-aware Bash guard runs after cwd check.
10. ``lint_structured_field_transform_shell`` — block brittle structured-field
    transform choreography (``items get`` -> tmp/var -> ``items update --stdin``).
    Runs after the broad cwd/path-claim guards because it inspects command
    shape, not path coverage.
11. ``lint_shell_quoted_function_payload`` — block hand-quoted JSON payloads
    to ``service_client`` and registry-covered Yoke CLIs wrapped with
    shell choreography. Runs after the structured-field transform shell
    lint because both inspect command shape; this one is keyed on the
    adapter inventory (function-id coverage).
12. ``lint_shell_backtick_search`` — block ``rg``/``grep`` search text
    that places backticks inside double quotes. Pure command-shape parse;
    runs with the other shell-footgun guards before any subprocess-backed
    state checks.
13. ``lint_no_agent_runtime_api_import_from_c`` — block ad-hoc
    ``python3 -c "from runtime..."`` one-liners. Shape-only denier in the
    same family as the shell-quoted payload lint above; keyed on the
    CLI-only-as-agent-interface doctrine.
14. ``lint_no_agent_curl_against_yoke_api`` — block ``curl`` invocations
    against ``localhost:8765`` / ``$YOKE_API``. Sibling shape-only
    denier sharing the agent-CLI-contract config mode key.
15. ``lint_no_agent_session_end`` — block agent-dispatched
    ``service_client session-end`` / ``session-end-if-empty``. The
    harness owns session lifetime; agents surrender work via
    ``yoke claims work release --all-mine``. Pure shape parse, same
    family as the two siblings above.
16. ``lint_claim_ownership_mutations`` — block claim-boundary bypass
    attempts (foreign ``--session-id`` on mutation families plus
    recent-denial replay against the same item). Runs after the
    shell-quoted payload lint because both gate mutation-family
    command shape; this one is keyed on claim ownership and reads
    recent event memory.
17. ``lint_git_stash_arg_order`` — block ``git stash push`` with
    ``-m``/``--message`` placed after ``--``. Pure shape parse, no
    subprocess fan-out; runs right before ``lint_destructive_git``
    because both inspect the same ``git stash`` namespace and the
    cheaper denier goes first.
18. ``lint_destructive_git`` — block destructive ``git reset --hard`` /
    ``checkout -- <path>`` / ``clean -f`` / ``stash drop`` shapes that would
    wipe uncommitted work. Runs after the cwd/path-claim/structural-shape
    guards because it shells out to ``git status`` for state inspection;
    keep cheaper structural deniers ahead of the subprocess fan-out.
19. ``hook_helpers_heartbeat`` — attestable-activity refresh; never
    blocks. Runs after every deny-class lint so a refused tool call
    does not stamp a fresh heartbeat. Replaces the deleted background
    keepalive loop.
20. ``observe_pre`` — telemetry tail; never blocks.

PreToolUse Edit/Write chain order rationale:

1. ``lint_session_cwd`` — broadest cwd gate, runs first.
2. ``path_claim_pre_edit_guard`` — claim-aware edit guard before file lints.
3. ``lint_*`` (e.g., ``lint_write_path``, ``lint_tc_label``) — file-shape lints.
4. ``observe_pre`` — telemetry tail.

PostToolUse Bash chain order rationale:

1. ``db_error_hook`` — DB-shape advisories (stray DB, SQLite failure,
   row-count collapse) front-door first; emits an additionalContext
   envelope when a write went sideways. Runs first so its targeted
   advisory wins when both could match.
2. ``hint_posttool_field_note`` — fires the canonical
   field-note FOOTER advisory when a Yoke CLI invocation exits
   non-zero. Runs after the DB-shape advisory and before telemetry so
   the agent sees the field-note nudge in the same turn the failure
   surfaced. Path-string parsing only — no DB, no IO.
3. ``observe`` — telemetry tail.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Sequence


# Frozen ordering mapping. The outer keys are hook event types; the inner
# keys are tool matchers (or ``"_default"`` when a single chain applies to
# every matcher). Values are tuples of dotted-module ids the renderer
# materialises into the harness's native chain format.
#
# We keep the mapping a tuple-of-tuples internally and expose a frozen
# MappingProxyType view. ``ordered_pipeline_for`` returns a fresh list so
# callers can mutate without leaking changes back into the registry.

_PRE_BASH: tuple[str, ...] = (
    # Neutral implementation-facing hook path. The implementation still emits
    # the legacy stable lint-sqlite-cmd telemetry/check id.
    "yoke_core.domain.lint_db_cmd",
    "yoke_core.domain.lint_event_registry",
    "yoke_core.domain.lint_main_commit",
    "yoke_core.domain.lint_tc_label",
    "yoke_core.domain.lint_long_command_polling",
    "yoke_core.domain.lint_pipe_to_truncator",
    "yoke_core.domain.lint_subagent_background",
    "yoke_core.domain.lint_session_cwd",
    "yoke_core.domain.lint_workspace_cwd_match",
    "yoke_core.domain.path_claim_bash_guard",
    "yoke_core.domain.lint_structured_field_transform_shell",
    "yoke_core.domain.lint_shell_quoted_function_payload",
    "yoke_core.domain.lint_shell_backtick_search",
    "yoke_core.domain.lint_no_agent_runtime_api_import_from_c",
    "yoke_core.domain.lint_no_agent_curl_against_yoke_api",
    "yoke_core.domain.lint_no_agent_session_end",
    "yoke_core.domain.lint_claim_ownership_mutations",
    "yoke_core.domain.lint_git_stash_arg_order",
    "yoke_core.domain.lint_destructive_git",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
)

_PRE_EDIT: tuple[str, ...] = (
    "yoke_core.domain.lint_session_cwd",
    "yoke_core.domain.path_claim_pre_edit_guard",
    "yoke_core.domain.lint_tc_label",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
)

_PRE_WRITE: tuple[str, ...] = (
    "yoke_core.domain.lint_session_cwd",
    "yoke_core.domain.path_claim_pre_edit_guard",
    "yoke_core.domain.lint_write_path",
    "yoke_core.domain.lint_python_runtime_import_in_tmp",
    "yoke_core.domain.hint_file_line_limit_approach",
    "yoke_core.domain.lint_tc_label",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
)

_PRE_READ: tuple[str, ...] = (
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
)

_PRE_SCHEDULE_WAKEUP: tuple[str, ...] = (
    "yoke_core.domain.lint_subagent_background",
    "yoke_core.domain.observe_pre",
)

_PRE_TASK_OUTPUT: tuple[str, ...] = (
    "yoke_core.domain.lint_subagent_background",
    "yoke_core.domain.observe_pre",
)

_PRE_MONITOR: tuple[str, ...] = (
    "yoke_core.domain.lint_long_command_polling",
    "yoke_core.domain.lint_subagent_background",
    "yoke_core.domain.hint_monitor_relay",
    "yoke_core.domain.observe_pre",
)

# Codex-shaped Bash equivalent for ``apply_patch`` — dispatched by the
# policy pipeline via :mod:`harness_policy_pipeline` once the Codex
# adapter translates the envelope. Listed here so the renderer
# has a stable ordering; module ids match the same policy modules.
_PRE_APPLY_PATCH: tuple[str, ...] = (
    "yoke_core.domain.lint_session_cwd",
    "yoke_core.domain.path_claim_pre_edit_guard",
    "yoke_core.domain.lint_tc_label",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
)

_POST_DEFAULT: tuple[str, ...] = (
    "yoke_core.domain.db_error_hook",
    "yoke_core.domain.hint_posttool_field_note",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe",
)

# Agent-tool PostToolUse chain: capture subagent reflections automatically.
# Reflection capture runs before the telemetry tail
# so the hook fire emits its event in the same envelope window as the
# tool-call completion event.
_POST_AGENT: tuple[str, ...] = (
    "yoke_core.domain.reflection_capture_hook",
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe",
)

_POST_FAILURE_DEFAULT: tuple[str, ...] = (
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe",
)

_PERMISSION_REQUEST: tuple[str, ...] = (
    "yoke_core.domain.observe_pre",
)

_SESSION_START: tuple[str, ...] = (
    "runtime.harness.hook_runner.session_dispatch",
)

_SESSION_END: tuple[str, ...] = (
    "runtime.harness.hook_runner.session_dispatch",
)

_USER_PROMPT_SUBMIT: tuple[str, ...] = (
    "runtime.harness.hook_runner.session_dispatch",
)

_STOP_DEFAULT: tuple[str, ...] = (
    "runtime.harness.hook_runner.session_dispatch",
)

# The PreToolUse mapping is matcher-keyed; non-Pre events use a single
# default chain keyed under ``_default`` (matchers are not meaningful for
# session lifecycle hooks).
_HOOK_ORDERING: dict[str, dict[str, tuple[str, ...]]] = {
    "PreToolUse": {
        "Bash": _PRE_BASH,
        "Edit": _PRE_EDIT,
        "Write": _PRE_WRITE,
        "Read": _PRE_READ,
        "ScheduleWakeup": _PRE_SCHEDULE_WAKEUP,
        "TaskOutput": _PRE_TASK_OUTPUT,
        "Monitor": _PRE_MONITOR,
        "apply_patch": _PRE_APPLY_PATCH,
    },
    "PostToolUse": {
        "Bash": _POST_DEFAULT,
        "Agent": _POST_AGENT,
        "_default": _POST_FAILURE_DEFAULT,
    },
    "PostToolUseFailure": {
        "_default": _POST_FAILURE_DEFAULT,
    },
    "PermissionRequest": {
        "_default": _PERMISSION_REQUEST,
    },
    "SessionStart": {
        "_default": _SESSION_START,
    },
    "SessionEnd": {
        "_default": _SESSION_END,
    },
    "UserPromptSubmit": {
        "_default": _USER_PROMPT_SUBMIT,
    },
    "Stop": {
        "_default": _STOP_DEFAULT,
    },
}


# Public read-only view. Inner dicts are also wrapped so consumers cannot
# mutate the chain registry by accident.
HOOK_ORDERING: Mapping[str, Mapping[str, Sequence[str]]] = MappingProxyType(
    {event: MappingProxyType(dict(matchers)) for event, matchers in _HOOK_ORDERING.items()}
)


def ordered_pipeline_for(event_type: str, matcher: str = "_default") -> list[str]:
    """Return the policy module chain for ``(event_type, matcher)``.

    Returns a *fresh* list each call so callers can mutate without
    affecting the registry. Returns an empty list when ``event_type`` is
    unknown or no matching chain is registered (forward-compatible:
    harnesses may declare matchers we haven't pre-populated yet).
    """
    matchers = _HOOK_ORDERING.get(event_type)
    if matchers is None:
        return []
    chain = matchers.get(matcher)
    if chain is None:
        chain = matchers.get("_default", ())
    return list(chain)


def event_types() -> list[str]:
    """Return every registered event type in declaration order."""
    return list(_HOOK_ORDERING.keys())


def matchers_for(event_type: str) -> list[str]:
    """Return every matcher registered for ``event_type``."""
    matchers = _HOOK_ORDERING.get(event_type)
    if matchers is None:
        return []
    return list(matchers.keys())
