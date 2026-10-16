"""Product-safe local hook subset evaluation.

The client half of the relay split: it evaluates the chain's ``CLIENT``
policies (:data:`yoke_contracts.hook_runner.policy_home.CLIENT_POLICIES`)
here, and collects the client facts the chain's server-run policies read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from yoke_contracts.hook_driver_process import (
    DRIVER_PAYLOAD_KEY,
    collect_driver_process,
)
from yoke_contracts.hook_runner.hook_ordering import matchers_for
from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.cursor_response import cursor_allow_stdout
from yoke_contracts.hook_runner.policy_home import CLIENT_POLICIES
from yoke_contracts.hook_runner.project_scope import (
    HookProjectScope,
    resolve_hook_project_scope,
)
from yoke_contracts.hook_runner.shell_guard_repairs import RIPGREP_REPLACE_CHECK_ID

from yoke_harness.hooks.client_facts import (
    collect_client_facts,
    event_chain,
    tool_matcher,
)
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.local_policies import (
    advisory_stdout,
    db_error_advisory,
    deny_stdout,
    hint_file_line,
    lint_destructive_git,
    lint_local_privacy,
    lint_shell_backtick_search,
    lint_tmp_runtime_import,
)
from yoke_harness.hooks.session_lifecycle import session_lifecycle
from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob
from yoke_harness.hooks.local_policy_common import (
    ADVISORY,
    DENY,
    NOOP,
    command_from_payload,
)


@dataclass(frozen=True)
class LocalSubsetEvaluation:
    """Outcome of the client-local half of one hook event."""

    stdout: str
    exit_code: int
    denied: bool
    payload_extra: dict | None = None
    denial_audit: dict | None = None


def _denial_audit(module_id: str, mode: str, payload: dict, reason: str) -> dict:
    """Build the audit fields a denied evaluation carries back to its caller.

    This client-local subset (``local_policies.py``'s guard reimplementations)
    cannot record a durable event itself — it must stay importable with no
    ``yoke_core``/DB-driver dependency, per the client/server package
    boundary. The caller that owns a live connection (``relay.py``) is the
    one that turns this into a ``HarnessToolCallDenied`` row.
    """
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    return {
        "hook": module_id,
        "check_id": RIPGREP_REPLACE_CHECK_ID
        if f"Yoke check id: {RIPGREP_REPLACE_CHECK_ID}" in reason
        else module_id,
        "guard_key": module_id,
        "mode": mode,
        "reason": reason,
        "command_snippet": command_from_payload(payload),
        "session_id": session_id if isinstance(session_id, str) else "",
        "tool_use_id": tool_use_id if isinstance(tool_use_id, str) else "",
        "turn_id": turn_id if isinstance(turn_id, str) else "",
    }


def _parse_payload(stdin_data: str) -> dict:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _local_modules(chain: list[str]) -> list[str]:
    return [module_id for module_id in chain if module_id in CLIENT_POLICIES]


_POLICY_EVALUATORS = {
    "yoke_core.domain.lint_shell_backtick_search": lint_shell_backtick_search,
    "yoke_core.domain.lint_local_privacy": lint_local_privacy,
    "yoke_core.domain.lint_destructive_git": lint_destructive_git,
    "yoke_core.domain.lint_python_runtime_import_in_tmp": lint_tmp_runtime_import,
    "yoke_core.domain.hint_file_line_limit_approach": hint_file_line,
    "yoke_core.domain.db_error_hook": db_error_advisory,
    "yoke_core.domain.lint_unmatched_path_glob": lint_unmatched_path_glob,
}
_SESSION_DISPATCH = "yoke_core.hooks.session_dispatch"


def render_dry_run(event_name: str, stdin_data: str = "") -> str:
    """Render the product-owned local subset without importing policy modules."""
    payload = _parse_payload(stdin_data)
    matcher = tool_matcher(event_name, payload)
    if matcher is None and event_name in {"PreToolUse", "PostToolUse"}:
        sections: list[str] = []
        for tool in matchers_for(event_name) or []:
            chain = event_chain(event_name, {"tool_name": tool})
            body = "\n".join(
                f"[product-local] {module_id}" for module_id in _local_modules(chain)
            )
            if body:
                sections.append(f"# {event_name}:{tool}\n{body}")
        return "\n\n".join(sections) + ("\n" if sections else "")
    lines = [
        f"[product-local] {module_id}"
        for module_id in _local_modules(event_chain(event_name, payload))
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def evaluate_local_subset(
    event_name: str,
    stdin_data: str,
    executor: str,
    agent_type: Optional[str],
    deadline: HookDeadline,
    *,
    collect_facts: bool = False,
    lint_config_snapshot: dict[str, dict[str, object]] | None = None,
    project_scope: HookProjectScope | None = None,
) -> LocalSubsetEvaluation:
    """Evaluate the chain's client policies in order; optionally collect facts.

    ``collect_facts`` is set by the relay, which ships the chain's client
    facts to the authority in ``payload_extra``. A relay passes the
    ``project_scope`` it already resolved for the request; a standalone
    evaluation resolves it here from its own payload.
    """
    _ = agent_type
    payload = _parse_payload(stdin_data)
    if project_scope is None:
        project_scope = resolve_hook_project_scope(payload)
    if lint_config_snapshot:
        payload[lint_policy.SNAPSHOT_PAYLOAD_KEY] = lint_config_snapshot
    # The driving process names itself on the machine where it actually runs:
    # over the relay the evaluating server's own pid names an API worker, not
    # the harness hook child that ran. Rides to the server in payload_extra.
    payload_extra: dict[str, object] = {DRIVER_PAYLOAD_KEY: collect_driver_process()}
    contexts: list[str] = []
    try:
        chain = event_chain(event_name, payload, project_scope)
    except (ValueError, OSError, RuntimeError) as exc:
        reason = f"hook_scope_unavailable: {exc}; repair the machine project mapping and retry"
        stdout, exit_code = deny_stdout(reason, event_name, executor)
        return LocalSubsetEvaluation(
            stdout, exit_code, True, payload_extra=payload_extra
        )
    if collect_facts:
        payload_extra.update(collect_client_facts(event_name, payload, executor, chain))
    for module_id in _local_modules(chain):
        if deadline.expired():
            break
        try:
            if module_id == _SESSION_DISPATCH:
                result = session_lifecycle(event_name, payload, executor)
            else:
                result = _POLICY_EVALUATORS[module_id](payload)
        except Exception as exc:  # fail open, but make the degradation visible
            contexts.append(
                f"product-local hook policy {module_id} degraded open: {exc}"
            )
            continue
        if result.outcome == NOOP:
            continue
        if result.outcome == DENY:
            mode = lint_policy.resolve_mode_from_snapshot(
                module_id,
                lint_config_snapshot,
            )
            if mode == lint_policy.WARN:
                contexts.append(
                    result.additional_context
                    or f"{module_id} would block, but lint-config mode is warn."
                )
                continue
            from yoke_contracts.hook_runner.shell_guard_repairs import (
                NOTHING_RAN,
                is_compound,
            )

            reason = result.message
            if is_compound(command_from_payload(payload)) and NOTHING_RAN not in reason:
                reason += f"\n\n{NOTHING_RAN}"
            stdout, exit_code = deny_stdout(reason, event_name, executor)
            return LocalSubsetEvaluation(
                stdout=stdout,
                exit_code=exit_code,
                denied=True,
                payload_extra=payload_extra,
                denial_audit=_denial_audit(module_id, mode, payload, reason),
            )
        if result.outcome == ADVISORY and result.additional_context:
            contexts.append(result.additional_context)
    stdout = advisory_stdout(contexts, event_name) if contexts else ""
    if executor.startswith("cursor"):
        stdout = cursor_allow_stdout(event_name, stdout)
    return LocalSubsetEvaluation(
        stdout=stdout,
        exit_code=0,
        denied=False,
        payload_extra=payload_extra,
    )


__all__ = [
    "LocalSubsetEvaluation",
    "evaluate_local_subset",
    "render_dry_run",
]
