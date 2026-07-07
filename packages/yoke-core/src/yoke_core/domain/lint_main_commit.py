"""PreToolUse hook: block implementation commits on main."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Iterable, Optional

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    NO_MAIN_CHECK_SUPPRESSION,
    STRATEGY_FRESHNESS_SUPPRESSION,
    is_actual_git_commit,
    is_bookkeeping as _contract_is_bookkeeping,
)
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain import lint_main_commit_strategy_freshness as strategy_freshness
from yoke_core.domain.lint_main_commit_process_claims import (
    is_strategy_commit_authorized,
)
from yoke_core.domain.lint_main_commit_client_facts import (
    client_facts,
    client_list,
    client_project_context,
    client_strategy_blobs,
)
from yoke_core.domain.lint_staged_union import effective_staged_set
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


def _extract_tool_input(payload: dict) -> dict:
    """Return ``tool_input`` accepting any of the known payload shapes."""
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _extract_command(payload: dict) -> str:
    """Return the Bash command string from a PreToolUse payload."""
    tool_input = _extract_tool_input(payload)
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        return command
    cmd_alt = tool_input.get("cmd")
    if isinstance(cmd_alt, str) and cmd_alt:
        return cmd_alt
    top_cmd = payload.get("command")
    if isinstance(top_cmd, str) and top_cmd:
        return top_cmd
    return ""


def is_bookkeeping(filepath: str) -> bool:
    """Classify *filepath* as a bookkeeping file allowed on main."""
    return _contract_is_bookkeeping(filepath)


def _current_branch() -> Optional[str]:
    """Return the current git branch name, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _staged_files() -> Optional[list[str]]:
    """Return the list of staged file paths, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.strip().split("\n") if line]


def _active_worktree_items() -> Optional[list[str]]:
    """Return ``id|title`` rows for in-flight worktree-backed items."""
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="items.list.run",
            target=TargetRef(kind="global"),
            payload={"fields": ["id", "title", "status", "worktree"]},
            timeout_s=2.0,
        )
        if not response.success:
            return None
        rows = (response.result or {}).get("rows") or []
    except Exception:
        return None
    terminal = {"done", "cancelled"}
    return [
        f"{row['id']}|{row['title']}"
        for row in rows
        if (row.get("worktree") or "").strip()
        and row.get("status") not in terminal
    ]


def _format_reason(
    non_bookkeeping: list[str],
    active_items: Iterable[str],
) -> str:
    impl_files_list = non_bookkeeping[:10]
    impl_files = "\n  ".join(impl_files_list)
    if len(non_bookkeeping) > 10:
        impl_files += "\n  ... and %d more" % (len(non_bookkeeping) - 10)

    active_list = ""
    for item in list(active_items)[:5]:
        parts = item.split("|", 1)
        if len(parts) == 2:
            active_list += "\n  - YOK-%s: %s" % (parts[0], parts[1])
        else:
            active_list += "\n  - %s" % item

    body = (
        "BLOCKED: Implementation commit on main branch.\n\n"
        "Staged implementation files:\n  %s\n\n"
        "Open worktree items:%s\n\n"
        "Worktree discipline: implementation code must be committed in a "
        "worktree branch, not directly on main. Only bookkeeping files "
        "(AGENTS.md, CLAUDE.md, ouroboros/*, .agents/*, .claude/*) "
        "are allowed on main.\n\n"
        "Options:\n"
        "  1. Continue work in the existing item worktree\n"
        "  2. File a separate ticket: /yoke idea\n"
        "  3. Override: add # lint:no-main-check to the command"
    ) % (impl_files, active_list)
    return append_field_note_footer(body, rule_id="lint-main-commit")


def evaluate_payload(payload: dict) -> Optional[str]:
    """Return a denial reason when *payload* should be blocked."""
    command = _extract_command(payload)
    if not command:
        return None
    if not is_actual_git_commit(command):
        return None

    facts = client_facts(payload)
    branch = (
        facts.get("branch") if facts is not None else _current_branch()
    )
    if branch is None or branch not in ("main", "master"):
        return None

    if facts is not None:
        staged = client_list(facts, "staged_paths")
        worktree_paths = frozenset(client_list(facts, "worktree_content_paths"))
        client_strategy_blobs_ = client_strategy_blobs(facts)
        project_ctx = client_project_context(facts)
    else:
        effective = effective_staged_set(command, _staged_files())
        if effective is None or not effective.paths:
            return None
        staged = effective.paths
        worktree_paths = effective.worktree_content_paths
        client_strategy_blobs_ = None
        project_ctx = None

    if not staged:
        return None

    # One evaluation = one row fetch: the freshness deny and the
    # matches-the-master authorization read the same strategy_docs rows
    # (one dispatcher call, potentially a large https payload), so the
    # per-evaluation memo dedupes the fetch between them.
    rows_cache: dict = {}
    if STRATEGY_FRESHNESS_SUPPRESSION not in command:
        freshness_kwargs = {
            "worktree_content_paths": worktree_paths,
            "rows_cache": rows_cache,
        }
        if project_ctx is not None:
            freshness_kwargs["project_ctx"] = project_ctx
        if client_strategy_blobs_ is not None:
            freshness_kwargs["client_strategy_blobs"] = client_strategy_blobs_
        freshness_denial = strategy_freshness.staged_freshness_denial(
            staged,
            **freshness_kwargs,
        )
        if freshness_denial is not None:
            return freshness_denial

    if NO_MAIN_CHECK_SUPPRESSION in command:
        return None

    non_bookkeeping = [f for f in staged if not is_bookkeeping(f)]
    if not non_bookkeeping:
        return None

    # Matches-the-master rule: staged strategy rendered views that
    # byte-match their live strategy_docs rows are always authorized.
    authorization_kwargs = {
        "worktree_content_paths": worktree_paths,
        "rows_cache": rows_cache,
    }
    if project_ctx is not None:
        authorization_kwargs["project_ctx"] = project_ctx
    if client_strategy_blobs_ is not None:
        authorization_kwargs["client_strategy_blobs"] = client_strategy_blobs_
    if is_strategy_commit_authorized(non_bookkeeping, **authorization_kwargs):
        return None

    active_items = _active_worktree_items()
    if not active_items:
        return None

    return _format_reason(non_bookkeeping, active_items)


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _emit_denial(payload: dict, reason: str) -> None:
    """Emit a ``HarnessToolCallDenied`` audit event (fire and forget, fail-open)."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    command_snippet = _extract_command(payload)
    # The freshness rule is a separate audit stream from impl-on-main.
    check_id = (
        "stale_strategy_render_on_main"
        if reason.startswith("BLOCKED: stale strategy rendered view")
        else "impl_on_main"
    )
    try:
        emit_denial_event(
            hook="lint-main-commit",
            tool="Bash",
            check_id=check_id,
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            command_snippet=command_snippet,
        )
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry: evaluate the staged commit against the worktree-discipline rule."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    if record.remote and CLIENT_GIT_COMMIT_FACTS_KEY not in payload:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = evaluate_payload(payload)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    _emit_denial(payload, reason)
    envelope = json.dumps(_build_deny_response(reason))
    return HookDecision(
        outcome=Outcome.DENY,
        message=envelope,
        audit_fields={"reason": reason},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name="Bash",
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
