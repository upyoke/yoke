"""PreToolUse Bash lint: block claim-boundary bypass attempts.

Static-spoofing branch denies mutation commands that pass a foreign
``--session-id``. Recent-denial branch denies same-item mutations when
this session recently attempted ``claim-work`` for the item
(``session_tool_calls.command_summary``) and another session still
holds the live exclusive claim (``work_claims``). Read-only commands,
same-session ``--session-id``, and unrelated items are allowed;
DB-unavailable recent-denial checks fail open.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


CHECK_ID = "claim_ownership_mutation"
HOOK_NAME = "lint-claim-ownership-mutations"
RECENT_DENIAL_LOOKBACK_SECONDS = 1800

_SERVICE_CLIENT_MUTATIONS: frozenset[str] = frozenset((
    "claim-work release-work-claim claim-release release-all-claims "
    "release-done-claims path-claim-register path-claim-widen "
    "path-claim-narrow path-claim-release path-claim-cancel "
    "path-claim-override path-claim-activate path-claim-cancel-amendment "
    "path-claim-unblock-stranded "
    "execute-structured-write execute-update execute-update-cli "
    "execute-create execute-create-cli execute-batch-update "
    "execute-batch-update-cli execute-close update-item db-claim-amend "
    "backlog-github coordination-lease-acquire coordination-lease-release "
    "coordination-lease-heartbeat"
).split())

_BACKLOG_CLI_MUTATIONS: frozenset[str] = frozenset((
    "add update batch-update sync-item sync-labels sync-body post-comment "
    "close close-issue backfill-oversized-bodies freeze thaw block "
    "unblock rebuild-board"
).split())

_DB_ROUTER_MUTATING_PATHS: tuple[tuple[str, ...], ...] = (
    ("items", "update"), ("items", "sync-item"),
    ("sections", "upsert"), ("sections", "delete"), ("sections", "rename"),
    ("qa", "requirement-add"), ("qa", "requirement-add-batch"),
    ("qa", "requirement-update"), ("qa", "run-add"),
    ("path-claims", "widen"), ("path-claims", "narrow"),
    ("path-claims", "release"),
    ("harness-sessions", "release-claim"),
)

_BARE_MODULE_MUTATIONS: frozenset[str] = frozenset((
    "yoke_core.domain.item_field_transform "
    "yoke_core.domain.epic "
    "yoke_core.domain.item_section_upsert "
    "yoke_core.domain.path_claim_register"
).split())

_READ_ONLY_SUBSTRINGS: tuple[str, ...] = tuple((
    "who-claims path-claim-list path-claim-get path-claim-conflicts "
    "path-claim-boundary actors-list actors-get session-offer "
    "session-heartbeat session-touch session-end-if-empty "
    "session-checkpoint-read harness-capabilities ownership-guard"
).split())

_DB_ROUTER_READ_ONLY_PATHS: tuple[tuple[str, ...], ...] = (
    ("items", "get"), ("items", "row"), ("items", "list"),
    ("items", "count"), ("items", "progress"),
    ("sections", "get"), ("sections", "list"),
    ("query",), ("events", "list"), ("events", "get"),
    ("shepherd", "dependency-list"), ("projects", "get"),
    ("harness-sessions", "who-claims"),
    ("path-claims", "list"), ("path-claims", "get"),
)

_PYTHON_M_RE = re.compile(r"python3?\s+-m\s+([\w.]+)\b")
_SESSION_ID_FLAG_RE = re.compile(r"--session-id[=\s]+([^\s]+)")
_ITEM_FLAG_RE = re.compile(r"(?:--item|--item-id)[=\s]+(?:YOK-)?(\d+)")
_BARE_YOKE_ITEM_REF_RE = re.compile(r"\bYOK-(\d+)\b")
_SHELL_BOUNDARIES = frozenset({"&&", "||", ";", "|", ">", "<", "2>&1"})


def _extract_command(payload: dict) -> str:
    tool_input = (
        payload.get("tool_input") or payload.get("toolInput")
        or payload.get("input") or {}
    )
    if not isinstance(tool_input, dict):
        tool_input = {}
    for candidate in (
        tool_input.get("command"), tool_input.get("cmd"),
        payload.get("command"),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


def _positional_tokens_after(command: str, module: str, count: int = 3) -> list[str]:
    idx = command.find(module)
    if idx < 0:
        return []
    out: list[str] = []
    for raw in command[idx + len(module):].strip().split():
        if raw.startswith("-"):
            continue
        if raw in _SHELL_BOUNDARIES:
            break
        out.append(raw)
        if len(out) >= count:
            break
    return out


def _matches_path(tokens: list[str], paths: Iterable[tuple[str, ...]]) -> bool:
    return any(tokens[: len(p)] == list(p) for p in paths)


def _is_read_only_command(command: str) -> bool:
    module = _module_invoked(command)
    if module in ("yoke_core.api.service_client", "runtime.harness.harness_sessions"):
        tokens = _positional_tokens_after(command, module)
        return bool(tokens and tokens[0] in _READ_ONLY_SUBSTRINGS)
    if module == "yoke_core.cli.db_router":
        return _matches_path(_positional_tokens_after(command, module), _DB_ROUTER_READ_ONLY_PATHS)
    return False


def _module_invoked(command: str) -> Optional[str]:
    match = _PYTHON_M_RE.search(command)
    return match.group(1) if match else None


def _classify_mutation(command: str) -> Optional[str]:
    module = _module_invoked(command)
    if module is None:
        return None
    if module == "yoke_core.api.service_client":
        tokens = _positional_tokens_after(command, module)
        if not tokens:
            return None
        head = tokens[0]
        if head == "backlog-cli":
            sub = tokens[1] if len(tokens) > 1 else ""
            return f"backlog-cli/{sub}" if sub in _BACKLOG_CLI_MUTATIONS else None
        return f"service-client/{head}" if head in _SERVICE_CLIENT_MUTATIONS else None
    if module == "yoke_core.cli.db_router":
        tokens = _positional_tokens_after(command, module)
        if tokens and _matches_path(tokens, _DB_ROUTER_MUTATING_PATHS):
            return "db-router/" + "/".join(tokens[:2])
        return None
    if module in _BARE_MODULE_MUTATIONS:
        return f"domain/{module.rsplit('.', 1)[-1]}"
    return None


def _extract_session_id_flag(command: str) -> Optional[str]:
    match = _SESSION_ID_FLAG_RE.search(command)
    return match.group(1) if match else None


def _extract_item_id(command: str) -> Optional[int]:
    for regex in (_ITEM_FLAG_RE, _BARE_YOKE_ITEM_REF_RE):
        match = regex.search(command)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    module = _module_invoked(command)
    if module:
        for tok in _positional_tokens_after(command, module, count=6):
            if tok.isdigit():
                return int(tok)
    return None


def _resolve_db_path() -> Optional[str]:
    """Vestigial token seam; Postgres authority is selected by DSN."""
    return None


def _recent_claim_denial_holder(
    db_path: Optional[str], session_id: str, item_id: int,
    lookback_seconds: int = RECENT_DENIAL_LOOKBACK_SECONDS,
) -> Optional[str]:
    """Return the live foreign holder after a recent same-item claim attempt.

    Two-step check against first-class state (the events ledger is
    telemetry-only): (1) ``session_tool_calls.command_summary`` shows this
    session recently ran ``claim-work`` naming the item; (2) ``work_claims``
    shows a live exclusive holder other than this session. Step 2 reading
    live claims is sharper than the historical response-text scan — a
    holder that released since the denial no longer blocks.
    """
    # Lexical ISO cutoff keeps the lookup native and parameter-safe.
    if not session_id:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=int(lookback_seconds))
    conn = None
    try:
        conn = connect(db_path or None)
        rows = conn.execute(
            "SELECT command_summary FROM session_tool_calls "
            "WHERE session_id=%s AND tool_name='Bash' "
            "AND command_summary IS NOT NULL "
            "AND started_at > %s ORDER BY started_at DESC LIMIT 100",
            (session_id, cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ).fetchall()

        item_token, item_bare = f"YOK-{item_id}", str(item_id)
        attempted = False
        for row in rows:
            command = row[0]
            if not isinstance(command, str) or "claim-work" not in command:
                continue
            if item_token in command or f"--item {item_bare}" in command:
                attempted = True
                break
        if not attempted:
            return None

        holder_row = conn.execute(
            "SELECT session_id FROM work_claims "
            "WHERE target_kind='item' AND item_id=%s "
            "AND released_at IS NULL AND claim_type='exclusive' "
            "AND session_id <> %s LIMIT 1",
            (item_id, session_id),
        ).fetchone()
        return holder_row[0] if holder_row else None
    except Exception:  # fail open: a DB hiccup must never block the user
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _emit_denial(payload: dict, reason: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
        emit_denial_event(
            hook=HOOK_NAME, tool="Bash", check_id=CHECK_ID, reason=reason,
            session_id=str(payload.get("session_id") or ""),
            tool_use_id=str(payload.get("tool_use_id") or ""),
            turn_id=str(payload.get("turn_id") or payload.get("message_id") or ""),
            command_snippet=_extract_command(payload),
        )
    except Exception:
        pass

def _spoof_reason(family: str, foreign_session: str) -> str:
    return append_field_note_footer(
        "BLOCKED: claim-boundary bypass attempt.\n\n"
        f"Mutation family: {family}\nForeign --session-id: {foreign_session}\n\n"
        "Artifact writes are work writes. Passing another session's id via "
        "--session-id from an ambient session is spoofing — the ambient "
        "session is the only valid owner. Foreign operator override for a "
        "stranded claim: `service_client claim-release --item YOK-N --claim-id <id> --reason <operator rationale>`.",
        rule_id="lint-claim-ownership-mutations")


def _recent_denial_reason(family: str, item_id: int, holder: str) -> str:
    return append_field_note_footer(
        "BLOCKED: claim-boundary bypass after live claim denial.\n\n"
        f"Mutation family: {family}\nItem: YOK-{item_id}\n"
        f"Live holder: {holder}\n\n"
        "A recent claim-work in this session was denied with "
        "'already claimed by session' for the same item. Subsequent "
        f"mutating shapes against YOK-{item_id} from this session are "
        "blocked until the holder releases or hands off.",
        rule_id="lint-claim-ownership-mutations")


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Return ``(reason, family)`` when *command* is denied, else None."""
    command = _extract_command(payload)
    if not command:
        return None
    if _is_read_only_command(command):
        return None

    family = _classify_mutation(command)
    if family is None:
        return None

    ambient = payload.get("session_id") if isinstance(payload, dict) else None
    ambient = ambient if isinstance(ambient, str) else ""

    declared = _extract_session_id_flag(command)
    if declared and ambient and declared != ambient:
        return (_spoof_reason(family, declared), family)

    item_id = _extract_item_id(command)
    if item_id is None or not ambient:
        return None

    holder = _recent_claim_denial_holder(_resolve_db_path(), ambient, item_id)
    if holder and holder != ambient:
        return (_recent_denial_reason(family, item_id, holder), family)
    return None


def evaluate(record: HookContext) -> HookDecision:
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, family = verdict
    _emit_denial(payload, reason)
    envelope = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": reason}}
    return HookDecision(outcome=Outcome.DENY, message=json.dumps(envelope),
        audit_fields={"reason": reason, "family": family}, block=True, next=Next.STOP)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    record = HookContext(
        event_name="PreToolUse",
        executor_family="claude", executor_surface="claude",
        payload=payload, tool_name="Bash",
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )
    decision = evaluate(record)
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
