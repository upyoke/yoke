"""Product-safe local hook subset evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from yoke_contracts.hook_runner.hook_ordering import (
    matchers_for,
    ordered_pipeline_for,
)
from yoke_contracts.hook_runner import lint_policy

from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.main_commit_client import collect_git_commit_facts
from yoke_harness.hooks.local_policies import (
    advisory_stdout,
    db_error_advisory,
    deny_stdout,
    hint_file_line,
    lint_destructive_git,
    lint_main_commit,
    lint_shell_backtick_search,
    lint_tmp_runtime_import,
    lint_workspace_cwd_match,
)
from yoke_harness.hooks.local_policy_common import ADVISORY, DENY, NOOP


LOCAL_STATE_POLICIES: frozenset[str] = frozenset(
    {
        "yoke_core.domain.lint_main_commit",
        "yoke_core.domain.lint_workspace_cwd_match",
        "yoke_core.domain.lint_shell_backtick_search",
        "yoke_core.domain.lint_destructive_git",
        "yoke_core.domain.lint_python_runtime_import_in_tmp",
        "yoke_core.domain.hint_file_line_limit_approach",
        "yoke_core.domain.db_error_hook",
    }
)

_LIFECYCLE_EVENTS = frozenset({
    "SessionStart",
    "UserPromptSubmit",
    "SessionEnd",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "Notification",
})


@dataclass(frozen=True)
class LocalSubsetEvaluation:
    """Outcome of the client-local half of one hook event."""

    stdout: str
    exit_code: int
    denied: bool
    payload_extra: dict | None = None


def _parse_payload(stdin_data: str) -> dict:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _matcher(event_name: str, payload: dict) -> Optional[str]:
    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name")
        return tool_name if isinstance(tool_name, str) and tool_name else None
    if event_name == "apply_patch":
        return "apply_patch"
    return None


def _chain_for(event_name: str, matcher: Optional[str]) -> list[str]:
    if event_name in _LIFECYCLE_EVENTS:
        chain = ordered_pipeline_for(event_name, "_default")
        return chain or ["runtime.harness.hook_runner.session_dispatch"]
    return ordered_pipeline_for(event_name, matcher or "_default")


def _local_modules(
    event_name: str,
    matcher: Optional[str],
    *,
    defer_main_commit: bool = False,
) -> list[str]:
    return [
        module_id for module_id in _chain_for(event_name, matcher)
        if module_id in LOCAL_STATE_POLICIES
        and not (
            defer_main_commit
            and module_id == "yoke_core.domain.lint_main_commit"
        )
    ]


_POLICY_EVALUATORS = {
    "yoke_core.domain.lint_main_commit": lint_main_commit,
    "yoke_core.domain.lint_workspace_cwd_match": lint_workspace_cwd_match,
    "yoke_core.domain.lint_shell_backtick_search": lint_shell_backtick_search,
    "yoke_core.domain.lint_destructive_git": lint_destructive_git,
    "yoke_core.domain.lint_python_runtime_import_in_tmp": lint_tmp_runtime_import,
    "yoke_core.domain.hint_file_line_limit_approach": hint_file_line,
    "yoke_core.domain.db_error_hook": db_error_advisory,
}


def render_dry_run(event_name: str, stdin_data: str = "") -> str:
    """Render the product-owned local subset without importing policy modules."""
    payload = _parse_payload(stdin_data)
    matcher = _matcher(event_name, payload)
    if matcher is None and event_name in {"PreToolUse", "PostToolUse"}:
        sections: list[str] = []
        for tool in matchers_for(event_name) or []:
            body = "\n".join(
                f"[product-local] {module_id}"
                for module_id in _local_modules(event_name, tool)
            )
            if body:
                sections.append(f"# {event_name}:{tool}\n{body}")
        return "\n\n".join(sections) + ("\n" if sections else "")
    lines = [
        f"[product-local] {module_id}"
        for module_id in _local_modules(event_name, matcher)
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def evaluate_local_subset(
    event_name: str,
    stdin_data: str,
    executor: str,
    agent_type: Optional[str],
    deadline: HookDeadline,
    *,
    defer_main_commit: bool = False,
    lint_config_snapshot: dict[str, dict[str, object]] | None = None,
) -> LocalSubsetEvaluation:
    """Evaluate the product-owned local policy subset in chain order."""
    _ = agent_type
    payload = _parse_payload(stdin_data)
    if lint_config_snapshot:
        payload[lint_policy.SNAPSHOT_PAYLOAD_KEY] = lint_config_snapshot
    matcher = _matcher(event_name, payload)
    payload_extra = (
        collect_git_commit_facts(payload) if defer_main_commit else {}
    )
    contexts: list[str] = []
    for module_id in _local_modules(
        event_name, matcher, defer_main_commit=defer_main_commit,
    ):
        if deadline.expired():
            break
        evaluator = _POLICY_EVALUATORS.get(module_id)
        if evaluator is None:
            continue
        try:
            result = evaluator(payload)
        except Exception as exc:  # fail open, but make the degradation visible
            contexts.append(
                f"product-local hook policy {module_id} degraded open: {exc}"
            )
            continue
        if result.outcome == NOOP:
            continue
        if result.outcome == DENY:
            mode = lint_policy.resolve_mode_from_snapshot(
                module_id, lint_config_snapshot,
            )
            if mode == lint_policy.WARN:
                contexts.append(
                    result.additional_context
                    or f"{module_id} would block, but lint-config mode is warn."
                )
                continue
            stdout, exit_code = deny_stdout(result.message, event_name, executor)
            return LocalSubsetEvaluation(
                stdout=stdout,
                exit_code=exit_code,
                denied=True,
                payload_extra=payload_extra,
            )
        if result.outcome == ADVISORY and result.additional_context:
            contexts.append(result.additional_context)
    stdout = advisory_stdout(contexts, event_name) if contexts else ""
    return LocalSubsetEvaluation(
        stdout=stdout,
        exit_code=0,
        denied=False,
        payload_extra=payload_extra,
    )


__all__ = [
    "LOCAL_STATE_POLICIES",
    "LocalSubsetEvaluation",
    "evaluate_local_subset",
    "render_dry_run",
]
