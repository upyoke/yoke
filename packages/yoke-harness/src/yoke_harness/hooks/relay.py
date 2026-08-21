"""Product-owned HTTPS hook relay."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Optional

from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES

from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT
from yoke_contracts.hook_runner.cursor_response import cursor_lifecycle_allow_stdout
from yoke_contracts.hook_runner.failures import render_failure_warning

from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.decision_render import (
    merge_allow_stdout,
    render_context_stdout,
)
from yoke_harness.hooks.identity import (
    detect_executor,
    is_cursor,
    prune_stale_session_anchors,
    record_session_anchor,
    relay_identity_payload,
    write_runtime_cache,
)
from yoke_harness.hooks.identity_stamp import record_then_stamp
from yoke_harness.hooks.guard_version_skew import annotate_guard_version_skew
from yoke_harness.hooks.local_subset import (
    evaluate_local_subset,
    render_dry_run,
)
from yoke_harness.hooks.relay_identity_guard import (
    capture_codex_session,
    deny_unstamped_relay,
    parse_hook_payload,
    print_execution_provenance,
    record_client_anchor,
)

_record_client_anchor = record_client_anchor
_codex_capture = capture_codex_session

HOOKS_EVALUATE_PATH = "/v1/hooks/evaluate"
AGENT_TYPE_ENV_VAR = "YOKE_HOOK_AGENT_TYPE"
_HOOK_WIRE_SCHEMA = 1
_CURSOR_CONTEXT_EVENTS = frozenset({SESSION_START_EVENT, "PostToolUse"})
_DEGRADED_MARKER = "YOKE_HOOK_DEGRADED"


def _cursor_degradation_stdout(
    event_name: str, detail: str, preserved_stdout: str
) -> str:
    if not is_cursor(detect_executor()):
        return preserved_stdout
    preserved_stdout = cursor_lifecycle_allow_stdout(
        event_name,
        preserved_stdout,
    )
    if event_name not in _CURSOR_CONTEXT_EVENTS:
        return preserved_stdout
    warning = (
        "WARNING: Yoke hook relay degraded to local-only allow; "
        f"server policy was not evaluated ({detail})"
    )
    try:
        payload = json.loads(preserved_stdout) if preserved_stdout else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if isinstance(payload, dict) and isinstance(
        payload.get("additional_context"),
        str,
    ):
        payload["additional_context"] += "\n\n" + warning
        return json.dumps(payload)
    return json.dumps({"additional_context": warning})


def degrade_to_noop(event_name: str, detail: str, *, preserved_stdout: str = "") -> int:
    """Fail open for hook transport/local harness failures."""
    sys.stderr.write(
        f"WARNING: {_DEGRADED_MARKER}: yoke hook evaluate {event_name}: "
        "https transport degraded "
        f"to no-op allow ({detail})\n"
    )
    print_execution_provenance(fallback_local=True)
    visible_stdout = _cursor_degradation_stdout(
        event_name,
        detail,
        preserved_stdout,
    )
    if visible_stdout:
        sys.stdout.write(visible_stdout)
    return 0


def _client_lint_config_snapshot(payload: dict) -> dict[str, dict[str, object]]:
    cwd = payload.get("cwd")
    start = cwd if isinstance(cwd, str) and cwd else None
    try:
        return lint_policy.snapshot_from_workspace(start=start)
    except Exception:
        return {}


def _with_extra_context(
    stdout: str,
    extra_context: Optional[str],
    event_name: str,
    *,
    cursor: bool = False,
) -> str:
    """Merge caller context into allow-path stdout without obscuring denies."""
    if not extra_context:
        return stdout
    rendered = render_context_stdout(extra_context, event_name, cursor=cursor)
    if not rendered:
        return stdout
    return merge_allow_stdout(stdout, rendered, event_name, cursor=cursor)


def evaluate_hook_event(
    event_name: str,
    *,
    dry_run: bool = False,
    stdin_data: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> int:
    """Evaluate the installed product-local hook subset only."""
    if stdin_data is None:
        stdin_data = sys.stdin.read()
    if dry_run:
        rendered = render_dry_run(event_name, stdin_data)
        if rendered:
            sys.stdout.write(rendered)
        return 0
    deadline = start_hook_deadline()
    payload = parse_hook_payload(stdin_data)
    policy_snapshot = _client_lint_config_snapshot(payload)
    agent_type = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    executor = detect_executor()
    stdin_data = record_then_stamp(payload, stdin_data, executor, event_name)
    from yoke_harness.hooks.cursor_lifecycle_hooks import (
        ensure_user_lifecycle_hooks_for_executor,
    )

    ensure_user_lifecycle_hooks_for_executor(executor)
    local = evaluate_local_subset(
        event_name,
        stdin_data,
        executor,
        agent_type or None,
        deadline,
        lint_config_snapshot=policy_snapshot,
    )
    stdout = local.stdout
    if local.denied:
        print_execution_provenance()
    if not local.denied:
        stdout = _with_extra_context(
            stdout,
            extra_context,
            event_name,
            cursor=is_cursor(executor),
        )
    if stdout:
        sys.stdout.write(stdout)
    return local.exit_code


def relay_hook_event(
    event_name: str,
    connection: HttpsConnection,
    *,
    stdin_data: Optional[str] = None,
    extra_context: Optional[str] = None,
) -> int:
    """Evaluate one hook event across the client/server relay split."""
    deadline = start_hook_deadline()
    if stdin_data is None:
        stdin_data = sys.stdin.read()
    payload = parse_hook_payload(stdin_data)
    policy_snapshot = _client_lint_config_snapshot(payload)
    _record_client_anchor(
        payload,
        session_start=event_name == SESSION_START_EVENT,
    )
    agent_type = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    executor = detect_executor()
    original_stdin = stdin_data
    stdin_data = record_then_stamp(payload, stdin_data, executor, event_name)
    from yoke_harness.hooks.cursor_lifecycle_hooks import (
        ensure_user_lifecycle_hooks_for_executor,
    )

    ensure_user_lifecycle_hooks_for_executor(executor)
    _codex_capture(event_name, original_stdin, executor)

    local = evaluate_local_subset(
        event_name,
        stdin_data,
        executor,
        agent_type or None,
        deadline,
        defer_main_commit=True,
        lint_config_snapshot=policy_snapshot,
    )
    if local.denied:
        print_execution_provenance()
        if local.stdout:
            sys.stdout.write(local.stdout)
        return local.exit_code

    allow_stdout = _with_extra_context(
        local.stdout,
        extra_context,
        event_name,
        cursor=is_cursor(executor),
    )

    denied = deny_unstamped_relay(parse_hook_payload(stdin_data))
    if denied is not None:
        return denied
    identity = relay_identity_payload(event_name, payload, executor)
    payload_extra = dict(local.payload_extra or {})
    if policy_snapshot:
        payload_extra[lint_policy.SNAPSHOT_PAYLOAD_KEY] = policy_snapshot
    from yoke_contracts.execution_provenance import collect_execution_provenance

    body = {
        "hook_schema": _HOOK_WIRE_SCHEMA,
        "event_name": event_name,
        "stdin": stdin_data,
        "executor": executor,
        "agent_type": agent_type or None,
        "entrypoint": identity["entrypoint"],
        "model": identity["model"],
        "execution_lane": identity["execution_lane"],
        "project_id": identity["project_id"],
        "payload_extra": payload_extra,
        "deadline_ms": max(1, deadline.remaining_ms()),
        "execution_provenance": collect_execution_provenance(),
    }
    url = connection.api_url.rstrip("/") + HOOKS_EVALUATE_PATH
    http_request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {connection.token}",
        },
    )
    timeout_s = deadline.remaining_ms() / 1000.0
    try:
        hosted = request_json(
            http_request,
            timeout_seconds=timeout_s,
            replay_safe=False,
            allow_loopback_http=True,
            response_limit_bytes=SMALL_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(connection.token,),
            opener=urllib.request.urlopen,
        )
        response = hosted.payload
    except BoundedJsonHttpStatusError as exc:
        return degrade_to_noop(
            event_name,
            f"HTTP {exc.status} from {safe_diagnostic_text(url)}",
            preserved_stdout=allow_stdout,
        )
    except BoundedJsonHttpError as exc:
        return degrade_to_noop(
            event_name,
            f"{safe_diagnostic_text(url)} unreachable or timed out: {exc}",
            preserved_stdout=allow_stdout,
        )

    if not isinstance(response, dict):
        return degrade_to_noop(
            event_name,
            "response body is not an object",
            preserved_stdout=allow_stdout,
        )
    stdout = response.get("stdout")
    exit_code = response.get("exit_code")
    outcome = response.get("outcome")
    if (
        not isinstance(stdout, str)
        or not isinstance(exit_code, int)
        or not isinstance(outcome, str)
    ):
        return degrade_to_noop(
            event_name,
            "response body is not the hook contract",
            preserved_stdout=allow_stdout,
        )
    server_fp = response.get("execution_provenance")
    if isinstance(server_fp, dict):
        print_execution_provenance(server_fp)
    else:
        print_execution_provenance()
    failure_warning = render_failure_warning(response.get("degraded", ()))
    if failure_warning:
        sys.stderr.write(failure_warning)
    if outcome == "denied":
        stdout = annotate_guard_version_skew(
            stdout,
            client=body["execution_provenance"],
            server=server_fp,
        )
        if stdout:
            sys.stdout.write(stdout)
        return exit_code

    merged = merge_allow_stdout(
        allow_stdout,
        stdout,
        event_name,
        cursor=is_cursor(executor),
    )
    if merged:
        sys.stdout.write(merged)
    return exit_code


__all__ = [
    "HOOKS_EVALUATE_PATH",
    "degrade_to_noop",
    "detect_executor",
    "evaluate_hook_event",
    "evaluate_local_subset",
    "merge_allow_stdout",
    "prune_stale_session_anchors",
    "record_session_anchor",
    "relay_hook_event",
    "write_runtime_cache",
]
