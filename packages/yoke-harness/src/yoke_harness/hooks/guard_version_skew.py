"""Make hook-policy version skew visible inside relayed denials."""

from __future__ import annotations

import json
from typing import Any, Mapping


_HOOK_OUTPUT_KEY = "hookSpecificOutput"
_NOTICE_PREFIX = "Yoke guard version mismatch:"
_UNKNOWN_REVISIONS = frozenset({"", "unknown"})


def _revision(provenance: object) -> str:
    if not isinstance(provenance, Mapping):
        return ""
    value = provenance.get("source_sha")
    return value.strip().lower() if isinstance(value, str) else ""


def _same_revision(left: str, right: str) -> bool:
    return left == right or left.startswith(right) or right.startswith(left)


def guard_version_skew_notice(
    *,
    client: object,
    server: object,
) -> str:
    """Explain a known client/server guard revision mismatch."""
    client_revision = _revision(client)
    server_revision = _revision(server)
    if (
        client_revision in _UNKNOWN_REVISIONS
        or server_revision in _UNKNOWN_REVISIONS
        or _same_revision(client_revision, server_revision)
    ):
        return ""
    return (
        f"{_NOTICE_PREFIX} this refusal was evaluated by server revision "
        f"{server_revision[:12]}, while the client hook is running "
        f"{client_revision[:12]}. The two sides are executing different "
        "guard code, so this denial cannot validate a just-merged allowance. "
        "Bring the serving Yoke process to the intended revision and restart "
        "it, then retry. Restarting only this harness session will not update "
        "a behind server."
    )


def _append_notice(text: str, notice: str) -> str:
    if _NOTICE_PREFIX in text:
        return text
    return f"{text.rstrip()}\n\n{notice}" if text.strip() else notice


def _annotate_hook_envelope(payload: dict[str, Any], notice: str) -> bool:
    inner = payload.get(_HOOK_OUTPUT_KEY)
    if not isinstance(inner, dict) or inner.get("permissionDecision") != "deny":
        return False
    reason = inner.get("permissionDecisionReason")
    if not isinstance(reason, str):
        return False
    inner["permissionDecisionReason"] = _append_notice(reason, notice)
    return True


def _annotate_cursor_envelope(payload: dict[str, Any], notice: str) -> bool:
    if payload.get("permission") != "deny":
        return False
    changed = False
    for key in ("user_message", "agent_message"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = _append_notice(value, notice)
            changed = True
    return changed


def annotate_guard_version_skew(
    stdout: str,
    *,
    client: object,
    server: object,
) -> str:
    """Append skew guidance without corrupting a harness deny envelope."""
    notice = guard_version_skew_notice(client=client, server=server)
    if not notice:
        return stdout
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return _append_notice(stdout, notice)
    if not isinstance(payload, dict):
        return stdout
    if not (
        _annotate_hook_envelope(payload, notice)
        or _annotate_cursor_envelope(payload, notice)
    ):
        return stdout
    return json.dumps(payload)


__all__ = ["annotate_guard_version_skew", "guard_version_skew_notice"]
