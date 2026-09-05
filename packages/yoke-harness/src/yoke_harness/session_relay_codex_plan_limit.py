"""Codex plan-limit read: the relay's proven app-server client, then the mirror.

Two lessons are built into this module. The first is that the read must use
the same bounded app-server client the relay already uses for launches and
messaging from this same daemon — a second, hand-rolled exchange diverged
from it (no ``--stdio``, text framing, inherited environment, no new
session) and failed structurally inside the daemon while the identical
protocol succeeded everywhere else. The second is that a probe which throws
its diagnostics away cannot be debugged: every failure here names itself in
the reading, logs its reason and the child's own stderr, and then falls
back to the HTTP usage mirror, so a broken app-server never costs the
operator the number as well as the explanation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.session_control.plan_limit_parsers import parse_codex_rate_limits
from yoke_contracts.session_control.plan_limits import reading_is_ok, unknown_reading
from yoke_harness.session_relay_codex_app_server_client import (
    CodexAppServerError,
    _Client,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_plan_limit_http import (
    PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
    plan_limit_http_json,
)


CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
_CODEX_USER_AGENT = "codex_cli_rs/yoke-plan-limit-probe"
_RATE_LIMIT_METHOD = "account/rateLimits/read"
_APP_SERVER_OPERATION = "codex plan-limit app-server read"
_MIRROR_OPERATION = "codex plan-limit usage-mirror read"

# The client's failure codes, translated into the reason an operator reads
# off the fleet report. An unmapped code is carried through rather than
# collapsed into a reason that names nothing.
_APP_SERVER_REASONS = {
    "binary_resolve": "cli_unavailable",
    "spawn": "app_server_spawn_failed",
    "pipes": "app_server_pipes_unavailable",
    "request_rejected": "app_server_request_rejected",
    "write_failed": "app_server_write_failed",
    "eof": "app_server_eof_before_reply",
    "timeout": "app_server_timeout",
    "response_oversize": "app_server_response_oversize",
    "stdout_unavailable": "app_server_stdout_unavailable",
    # The client raises this code only for the peer's JSON-RPC "method not
    # found" error — the one signal that actually means this build lacks
    # the operation. Every other RPC error raises "rpc_error" instead (see
    # _failure_reason), so it keeps its own code rather than reading as
    # this.
    "method_error": "unsupported_on_this_build",
}

_failures = FailureReporter()


def _failure_reason(failure: CodexAppServerError) -> str:
    """Name the app-server failure, keeping the class that actually raised.

    An ``rpc_error`` carries whatever code the peer's own JSON-RPC error
    named (authentication, invalid params, an internal error, …). Losing
    that code is what used to let an unrelated RPC failure read as
    "unsupported build" (field-note 46471), so it stays in the reason
    instead of collapsing into one bucket.
    """
    if failure.code == "rpc_error":
        if failure.rpc_error_code is not None:
            return f"app_server_rpc_error:{failure.rpc_error_code}"
        return "app_server_rpc_error"
    reason = _APP_SERVER_REASONS.get(failure.code, f"app_server_{failure.code}")
    cause = failure.__cause__
    if cause is None or isinstance(cause, CodexAppServerError):
        return reason
    return f"{reason}:{type(cause).__name__}"


def app_server_reading(observed_at: str) -> tuple[dict[str, Any] | None, str, str]:
    """Read the codex bucket over app-server; on failure name it and say why.

    Returns the reading or ``None``, the reason for the reading's own
    ``reason`` field, and the longer detail — the child's stderr included —
    that belongs in the relay log rather than in a one-line report cell.
    """
    client: _Client | None = None
    try:
        client = _Client(
            "codex",
            Path.home(),
            native_session_environment(executor="codex", provider="openai"),
            PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
            capture_stderr=True,
        )
        result = client.request(_RATE_LIMIT_METHOD, {})
    except CodexAppServerError as failure:
        reason = _failure_reason(failure)
        tail = client.stderr_tail() if client is not None else ""
        detail = f"{reason} ({failure}); child stderr: {tail or '<empty>'}"
        return None, reason, detail
    finally:
        if client is not None:
            client.close()
    if not result:
        return None, "app_server_empty_result", "app_server_empty_result"
    reading = parse_codex_rate_limits(result, observed_at=observed_at)
    if not reading_is_ok(reading):
        return (
            None,
            "app_server_result_unparsed",
            f"unparsed result keys: {sorted(result)}",
        )
    return reading, "", ""


def _usage_mirror_reading(observed_at: str) -> tuple[dict[str, Any] | None, str]:
    """Read the same bucket from the HTTP usage mirror, or name the refusal."""
    path = Path.home() / ".codex" / "auth.json"
    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"codex_auth_unreadable_{type(exc).__name__}"
    except json.JSONDecodeError:
        return None, "codex_auth_not_json"
    tokens = auth.get("tokens") if isinstance(auth, Mapping) else None
    if not isinstance(tokens, Mapping):
        return None, "codex_auth_missing_tokens"
    token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(token, str) or not isinstance(account_id, str):
        return None, "codex_auth_missing_access_token"
    payload = plan_limit_http_json(
        CODEX_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account_id,
            "User-Agent": _CODEX_USER_AGENT,
        },
    )
    if isinstance(payload, str):
        return None, payload
    reading = parse_codex_rate_limits(payload, observed_at=observed_at)
    if not reading_is_ok(reading):
        return None, "usage_mirror_result_unparsed"
    return reading, ""


def probe_codex_cli(*, observed_at: str) -> dict[str, Any]:
    """Read codex plan limits, falling back to the mirror on every failure."""
    reading, reason, detail = app_server_reading(observed_at)
    if reading is not None:
        _failures.recovered(_APP_SERVER_OPERATION)
        return reading
    # Logged even when the mirror heals the number: a silent fallback is how
    # a broken app-server stayed invisible for as long as it did.
    _failures.failed(_APP_SERVER_OPERATION, detail)
    mirror, mirror_reason = _usage_mirror_reading(observed_at)
    if mirror is not None:
        _failures.recovered(_MIRROR_OPERATION)
        return mirror
    _failures.failed(_MIRROR_OPERATION, mirror_reason)
    return unknown_reading(
        "codex-cli", f"{reason}+{mirror_reason}", observed_at=observed_at
    )


__all__ = ["CODEX_USAGE_URL", "app_server_reading", "probe_codex_cli"]
