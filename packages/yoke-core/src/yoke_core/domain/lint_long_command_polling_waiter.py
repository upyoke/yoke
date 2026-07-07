"""Background-waiter PreToolUse verdict.

Split sibling of :mod:`lint_long_command_polling_evaluate`. Owns the
"``Bash(run_in_background=true)`` whose body is a waiter on an existing
capture file or sentinel" rule. The shape exists because agents
otherwise reach for ``run_in_background`` to wait for a paired kickoff
to finish — the bg-bash buffers stdout exactly the same way the
foreground tail/cat peek does, just expressed through the
``run_in_background`` channel. The Monitor on the original capture (or
the harness completion notification) is the canonical signal; spawning
another bg whose sole purpose is to wait is a redundant double-watcher.

Detected waiter shapes (only fire when ``tool_input.run_in_background``
is true on a Bash call):

1. ``tail -[fF] <tempdir-prefix>/<path>`` — duplicate tail waiter.
2. ``sleep N && (peek-verb) <tempdir-prefix>/<path>`` — sleep-then-peek
   waiter (any peek verb in :data:`_PEEK_VERB_RE`).
3. ``while [ ! -f <tempdir-prefix>/<path> ]; do sleep N; done`` —
   sentinel polling.
4. ``python3 -m yoke_core.tools.watch_tail <tempdir-prefix>/<path>``
   — duplicate watch_tail.

Mode-pinned by ``lint_polling_mode`` (``warn`` records audit only;
``deny`` blocks). The ``# lint:no-bg-waiter-check`` token is honoured
ONLY as audit evidence (recorded as ``outcome=suppression_attempted``);
the rule still denies in ``deny`` mode.

The verdict only fires when the candidate's target capture matches an
existing in-session signal — either the most recent kickoff's
redirect / ``--raw-capture`` / ``--progress-capture`` path, or a
non-self armed Monitor's capture. Without that match, the waiter shape
is allowed (it might be a legitimate first-of-its-kind background tail
the user wants).
"""

from __future__ import annotations

import re
from typing import Optional

from yoke_core.domain.lint_long_command_polling_config import _read_lint_mode
from yoke_core.domain.lint_long_command_polling_constants import (
    BG_WAITER_SUPPRESSION_TOKEN,
)
from yoke_core.domain.lint_long_command_polling_decide import _build_context
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_background_capture_files,
    _extract_command,
    _extract_monitor_capture_file,
    _extract_tool_input,
    _extract_tool_name,
    _temp_dir_prefixes,
)


__all__ = ["evaluate_bg_waiter"]


_TEMP_PREFIX_GROUP = "(?:" + "|".join(
    re.escape(p) for p in _temp_dir_prefixes()
) + ")"

# Same widened verb list as :data:`lint_long_command_polling_extract._PEEK_VERB_RE`.
_PEEK_VERB_ALT = (
    "tail|head|cat|wc|grep|egrep|fgrep|rg|ls|awk|sed|less|more|file|stat|"
    "nl|cut|sort|uniq"
)

_TAIL_F_RE = re.compile(
    rf"\btail\s+-[FfnvqzN]+\b[^|;&]*?({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)
_SLEEP_THEN_PEEK_PATH_RE = re.compile(
    rf"\bsleep\s+\d+\s*(?:&&|;)\s*(?:{_PEEK_VERB_ALT})\b[^|;&]*?({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)
_WATCH_TAIL_RE = re.compile(
    rf"\bpython3?\s+-m\s+(?:yoke_core|runtime\.api)\.tools\.watch_tail\b[^|;&]*?({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)
_WHILE_SENTINEL_RE = re.compile(
    rf"\bwhile\s+\[\s+!\s+-f\s+({_TEMP_PREFIX_GROUP}/[\w./-]+)\s+\]\s*;\s*do\s+sleep\b",
)


def _is_run_in_background(payload: dict) -> bool:
    tool_input = _extract_tool_input(payload)
    flag = tool_input.get("run_in_background")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str):
        return flag.strip().lower() in ("true", "1", "yes")
    return False


def _extract_waiter_target(command: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(shape, target_path)`` for the matched waiter, else ``(None, None)``.

    ``shape`` is one of ``"tail-f"``, ``"sleep-then-peek"``,
    ``"watch-tail"``, ``"while-sentinel"``.
    """
    m = _TAIL_F_RE.search(command)
    if m:
        return ("tail-f", m.group(1))
    m = _SLEEP_THEN_PEEK_PATH_RE.search(command)
    if m:
        return ("sleep-then-peek", m.group(1))
    m = _WATCH_TAIL_RE.search(command)
    if m:
        return ("watch-tail", m.group(1))
    m = _WHILE_SENTINEL_RE.search(command)
    if m:
        return ("while-sentinel", m.group(1))
    return (None, None)


def _resolve_db_path() -> Optional[str]:
    try:
        from yoke_core.domain.db_helpers import resolve_db_path
    except Exception:
        return None
    try:
        return resolve_db_path()
    except Exception:
        return None


def _existing_capture_files(payload: dict) -> set[str]:
    """Return capture files seen in the in-session signal surface.

    Includes capture files extracted from the most recent Bash kickoffs
    in this session (``--raw-capture`` / ``--progress-capture`` /
    redirect paths) and the capture files of currently-armed Monitors.
    The waiter rule fires only when the candidate's target path is in
    this set — without a matching prior signal, the waiter shape is
    allowed (a legitimate first-of-its-kind background tail).
    """
    session_id = payload.get("session_id") or ""
    db_path = _resolve_db_path()
    if not db_path or not session_id:
        return set()
    captures: set[str] = set()
    try:
        from yoke_core.domain.lint_long_command_polling_evaluate import (
            _recent_bash_commands,
        )
    except Exception:
        _recent_bash_commands = None  # type: ignore[assignment]
    if _recent_bash_commands is not None:
        for _tool_use_id, _created_at, command in _recent_bash_commands(
            db_path, session_id,
        ):
            for capture_file in _extract_background_capture_files(command):
                captures.add(capture_file)
    try:
        from yoke_core.domain.lint_long_command_polling_monitor_duplicate import (
            _captures_targeted_in_session,
        )
    except Exception:
        _captures_targeted_in_session = None  # type: ignore[assignment]
    if _captures_targeted_in_session is not None:
        for _tool_use_id, capture_file in _captures_targeted_in_session(
            db_path, session_id,
        ):
            captures.add(capture_file)
    return captures


def _format_reason(
    shape: str,
    target_path: str,
    suppressed_attempt: bool,
    mode: str,
) -> str:
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    body = (
        f"Background-waiter Bash invocation: {shape}.\n\n"
        f"Target capture/sentinel: {target_path}\n\n"
        "Spawning a `Bash(run_in_background=true)` whose body is a waiter "
        "on an existing capture file or sentinel duplicates the work of "
        "the existing Monitor or background command. The Monitor on the "
        "capture (or the harness completion notification) IS the progress "
        "signal — the armed Monitor IS the waiter. A second background "
        "tail / sleep-then-peek / sentinel-poll / watch_tail is a "
        "redundant double-watcher.\n\n"
        "This rule has NO override — the "
        f"`{BG_WAITER_SUPPRESSION_TOKEN}` token is honoured ONLY as audit "
        "evidence; it does NOT unblock this rule.\n\n"
        "Options:\n"
        "  1. Wait for the existing Monitor's next wake — it will fire on "
        "the next matched line\n"
        "  2. Await the harness completion notification for the original "
        "background task\n"
        "  3. Stop the existing Monitor/background task via `TaskStop` "
        "first if you genuinely need a fresh waiter"
    )
    if suppressed_attempt:
        return (
            f"{verb}: " + body
            + f"\n\nSuppression token `{BG_WAITER_SUPPRESSION_TOKEN}` "
            "was detected on this command and recorded for audit, but it "
            "does NOT unblock this rule."
        )
    return f"{verb}: " + body


def evaluate_bg_waiter(
    payload: dict,
) -> Optional[tuple[str, str, dict]]:
    """Verdict for the bg-waiter PreToolUse rule.

    Returns ``(mode, reason, context)`` when the candidate Bash invocation
    is ``run_in_background=true`` and its body matches a waiter shape
    targeting a capture file or sentinel that is already being watched
    in this session. Returns ``None`` otherwise.
    """
    tool_name = _extract_tool_name(payload)
    if tool_name and tool_name != "Bash":
        return None
    if not _is_run_in_background(payload):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    shape, target_path = _extract_waiter_target(command)
    if not shape or not target_path:
        return None
    if target_path not in _existing_capture_files(payload):
        return None
    mode = _read_lint_mode(payload)
    suppressed_attempt = BG_WAITER_SUPPRESSION_TOKEN in command
    ctx = _build_context(tool_name or "Bash", command, target_path)
    ctx["outcome"] = (
        "suppression_attempted" if suppressed_attempt else "denied"
    )
    ctx["waiter_shape"] = shape
    reason = _format_reason(shape, target_path, suppressed_attempt, mode)
    return (mode, reason, ctx)
