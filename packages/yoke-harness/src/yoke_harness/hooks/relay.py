"""Product-owned HTTPS hook relay."""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES

from yoke_contracts.hook_runner import lint_policy

from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.decision_render import merge_allow_stdout
from yoke_harness.hooks.identity import (
    detect_executor,
    is_codex,
    record_session_anchor,
    relay_identity_payload,
    resolve_session_id,
    write_runtime_cache,
)
from yoke_harness.hooks.local_subset import (
    evaluate_local_subset,
    render_dry_run,
)


HOOKS_EVALUATE_PATH = "/v1/hooks/evaluate"
AGENT_TYPE_ENV_VAR = "YOKE_HOOK_AGENT_TYPE"
_HOOK_WIRE_SCHEMA = 1


def degrade_to_noop(event_name: str, detail: str, *, preserved_stdout: str = "") -> int:
    """Fail open for hook transport/local harness failures."""
    sys.stderr.write(
        f"yoke hook evaluate {event_name}: https transport degraded "
        f"to no-op allow ({detail})\n"
    )
    if preserved_stdout:
        sys.stdout.write(preserved_stdout)
    return 0


def _parse_payload(stdin_data: str) -> dict:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _record_client_anchor(payload: dict) -> None:
    try:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id == "unknown":
            return
        tp = payload.get("transcript_path")
        record_session_anchor(
            session_id,
            transcript_path=tp if isinstance(tp, str) else "",
        )
    except Exception:
        return


def _client_lint_config_snapshot(payload: dict) -> dict[str, dict[str, object]]:
    cwd = payload.get("cwd")
    start = cwd if isinstance(cwd, str) and cwd else None
    try:
        return lint_policy.snapshot_from_workspace(start=start)
    except Exception:
        return {}


def _codex_capture(event_name: str, stdin_data: str, executor: str) -> None:
    if event_name != "SessionStart" or not is_codex(executor):
        return
    try:
        sid = resolve_session_id(stdin_data)
        if sid:
            write_runtime_cache(sid, stdin_data)
    except Exception:
        return


def evaluate_hook_event(event_name: str, *, dry_run: bool = False) -> int:
    """Evaluate the installed product-local hook subset only."""
    stdin_data = sys.stdin.read()
    if dry_run:
        rendered = render_dry_run(event_name, stdin_data)
        if rendered:
            sys.stdout.write(rendered)
        return 0
    deadline = start_hook_deadline()
    payload = _parse_payload(stdin_data)
    policy_snapshot = _client_lint_config_snapshot(payload)
    agent_type = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    executor = detect_executor()
    local = evaluate_local_subset(
        event_name,
        stdin_data,
        executor,
        agent_type or None,
        deadline,
        lint_config_snapshot=policy_snapshot,
    )
    if local.stdout:
        sys.stdout.write(local.stdout)
    return local.exit_code


def relay_hook_event(event_name: str, connection: HttpsConnection) -> int:
    """Evaluate one hook event across the client/server relay split."""
    deadline = start_hook_deadline()
    stdin_data = sys.stdin.read()
    payload = _parse_payload(stdin_data)
    policy_snapshot = _client_lint_config_snapshot(payload)
    _record_client_anchor(payload)
    agent_type = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    executor = detect_executor()
    _codex_capture(event_name, stdin_data, executor)

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
        if local.stdout:
            sys.stdout.write(local.stdout)
        return local.exit_code

    identity = relay_identity_payload(event_name, payload, executor)
    payload_extra = dict(local.payload_extra or {})
    if policy_snapshot:
        payload_extra[lint_policy.SNAPSHOT_PAYLOAD_KEY] = policy_snapshot
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
            preserved_stdout=local.stdout,
        )
    except BoundedJsonHttpError as exc:
        return degrade_to_noop(
            event_name,
            f"{safe_diagnostic_text(url)} unreachable or timed out: {exc}",
            preserved_stdout=local.stdout,
        )

    if not isinstance(response, dict):
        return degrade_to_noop(
            event_name,
            "response body is not an object",
            preserved_stdout=local.stdout,
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
            preserved_stdout=local.stdout,
        )
    if outcome == "denied":
        if stdout:
            sys.stdout.write(stdout)
        return exit_code

    merged = merge_allow_stdout(local.stdout, stdout, event_name)
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
    "relay_hook_event",
]
