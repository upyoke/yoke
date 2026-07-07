"""Pure-function command/payload introspection for the polling lint.

Owns the regex constants and every helper that classifies a command
string or PreToolUse payload without touching the filesystem, DB, or
the audit-event surface. The evaluate sibling consumes these for its
verdict logic; the entry-point ``run()`` consumes ``_extract_command``
and ``_extract_tool_name`` for audit emission.

Functions here are read-only over their inputs and have no side
effects.
"""

from __future__ import annotations

import re
from typing import Optional

from yoke_core.domain.lint_long_command_polling_constants import (
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
    SUPPRESSION_TOKEN,
)
from yoke_core.domain.lint_long_command_polling_extract_scratch import (
    is_helper_resolved_scratch_path,
    scratch_path_roots,
)


def _temp_dir_prefixes() -> list[str]:
    """Return path prefixes the redirect/peek regexes accept.

    Delegates to
    :func:`lint_long_command_polling_extract_scratch.scratch_path_roots`
    so the polling lint, the waiter rule, and downstream denial
    messages all agree on which paths count as Yoke scratch (the
    helper-resolved root plus the legacy ``/tmp`` / ``/private/tmp`` /
    ``tempfile.gettempdir()`` prefixes the regexes already accept).
    Also returns the ``/private`` canonical equivalent for any
    ``/var/...`` legacy prefix on macOS where ``/tmp`` is a symlink to
    ``/private/tmp``.
    """
    prefixes: list[str] = []
    for root in scratch_path_roots():
        if root not in prefixes:
            prefixes.append(root)
        if root.startswith("/var/"):
            canonical = "/private" + root
            if canonical not in prefixes:
                prefixes.append(canonical)
    return prefixes


_TEMP_PREFIXES = _temp_dir_prefixes()
_TEMP_PREFIX_GROUP = "(?:" + "|".join(re.escape(p) for p in _TEMP_PREFIXES) + ")"

# Peek verbs: any reading verb against a capture file is a peek (audit
# evidence showed `grep`/`wc`/`ls`/`awk`/`sed`/`stat` etc. were used to
# peek unblocked). `[^;&]*?` (no pipe exclusion) so `grep -E "p|f" path`
# still matches. `(?<![-/=])` rejects `--body-file /tmp/x` shapes.
_PEEK_VERB_RE = re.compile(
    rf"(?<![-/=])\b(tail|head|cat|wc|grep|egrep|fgrep|rg|ls|awk|sed|less|more|file|stat|nl|cut|sort|uniq)\b[^;&]*?({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)
_REDIRECT_TO_CAPTURE_RE = re.compile(
    rf">>?\s*({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)
# Watcher-arg flag names are unique to our wrappers — the flag IS the
# discriminator, so the path argument can live in any tempdir.
_WATCHER_CAPTURE_ARG_RE = re.compile(
    r"--(?:raw-capture|progress-capture)(?:=|\s+)([^\s;&|<>]+)",
)
_SLEEP_THEN_PEEK_RE = re.compile(
    r"\bsleep\s+(\d+)\s*(?:&&|;)\s*(?<![-/=])(?:cat|tail|head|wc|grep|egrep|fgrep|rg|ls|awk|sed|less|more|file|stat|nl|cut|sort|uniq)\b",
)
# Monitor command: watch_tail or bare `tail -f/-F` against a /tmp capture
# file. Trailing filters (`| grep ...`) are intentionally ignored —
# capture-file equivalence is what matters.
_MONITOR_CAPTURE_RE = re.compile(
    rf"\b(?:python3\s+-m\s+(?:yoke_core|runtime\.api)\.tools\.watch_tail|tail\s+-[FfnvqzN]+)\s+({_TEMP_PREFIX_GROUP}/[\w./-]+)",
)


def _extract_tool_input(payload: dict) -> dict:
    """Return ``tool_input`` accepting any of the known payload shapes."""
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _extract_command(payload: dict) -> str:
    """Return the Bash command string (or other text body) from the payload."""
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


def _extract_tool_name(payload: dict) -> str:
    """Return the invoked tool name (``Bash``, ``ScheduleWakeup``, etc.)."""
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _has_suppression(command: str) -> bool:
    return SUPPRESSION_TOKEN in command


def _has_monitor_duplicate_suppression(command: str) -> bool:
    """True if *command* carries the duplicate-Monitor token (audit-only)."""
    return MONITOR_DUPLICATE_SUPPRESSION_TOKEN in command


_PEEK_VERBS = frozenset({
    "tail", "head", "cat", "wc", "grep", "egrep", "fgrep", "rg", "ls",
    "awk", "sed", "less", "more", "file", "stat", "nl", "cut", "sort", "uniq",
})


def _is_stdin_feed_cat(command: str, match) -> bool:
    """True iff matched ``cat <tmpfile>`` is feeding stdin downstream.

    ``cat <tmpfile> | <substantive consumer>`` is a stdin feed (tempfile
    is content payload), not a polling peek. Restricted to ``cat``;
    pipelines of peek verbs (``cat | tail``) stay peeks.
    """
    if match.group(1) != "cat":
        return False
    tail = command[match.end():].lstrip()
    if not tail.startswith("|") or tail.startswith("||"):
        return False
    after_pipe = tail[1:].lstrip()
    if not after_pipe:
        return False
    consumer = after_pipe.split(None, 1)[0].rsplit("/", 1)[-1]
    return consumer not in _PEEK_VERBS


def _extract_peek_capture_file(command: str) -> Optional[str]:
    """Return the /tmp capture-file path if *command* looks like a peek.

    Any reading verb in :data:`_PEEK_VERB_RE` against a tempdir-prefixed
    path is a peek. Carve-out: ``cat <tmpfile> | <substantive consumer>``
    is a stdin feed (see :func:`_is_stdin_feed_cat`).
    """
    m = _PEEK_VERB_RE.search(command)
    if not m:
        return None
    if _REDIRECT_TO_CAPTURE_RE.search(command):
        return None
    if _is_stdin_feed_cat(command, m):
        return None
    return m.group(2)


def _peek_read_in_command_substitution(command: str) -> bool:
    """True iff the peek-verb match sits inside a ``$(...)`` substitution.

    ``OUT=$(cat /tmp/ptr.txt); cd "$OUT" && ...`` consumes the file's
    bytes as input to the rest of the command (the pointer-file idiom
    that persists a mktemp path across Bash subshells) — the read never
    reaches the transcript, so on its own it is not a progress peek.
    Callers MUST pair this with the session capture-registration check:
    a file some session command redirected into (or named via
    ``--raw-capture``/``--progress-capture``) stays a peek even when
    read through a substitution.
    """
    m = _PEEK_VERB_RE.search(command)
    if not m:
        return False
    prefix = command[: m.start()]
    open_idx = prefix.rfind("$(")
    # Enclosed iff a `$(` opens before the verb with no `)` in between
    # (a closed earlier substitution does not enclose the read).
    return open_idx != -1 and ")" not in prefix[open_idx + 2:]


def _extract_sleep_cadence(command: str) -> Optional[int]:
    """Return the ``sleep N`` seconds value before a tail/head/cat, if present."""
    m = _SLEEP_THEN_PEEK_RE.search(command)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _extract_monitor_capture_file(command: str) -> Optional[str]:
    """Return the capture-file path a Monitor command targets, if any.

    Accepts the canonical wrapper (``python3 -m
    yoke_core.tools.watch_tail <path>``) and the fallback bare
    ``tail -f <path>`` shape (including ``-F`` / additional flags). The
    trailing pipeline (``| grep --line-buffered ...``) is intentionally
    NOT inspected: two Monitors against the same capture file are
    duplicates even when their filter expressions differ. Returns
    ``None`` when *command* does not match either shape
    or does not reference a tempdir path.
    """
    match = _MONITOR_CAPTURE_RE.search(command)
    if not match:
        return None
    return match.group(1)


def _extract_background_capture_files(command: str) -> list[str]:
    """Return capture files that indicate a long background command is active."""
    captures: list[str] = []
    redirect = _REDIRECT_TO_CAPTURE_RE.search(command)
    if redirect:
        captures.append(redirect.group(1))
    captures.extend(
        match.group(1) for match in _WATCHER_CAPTURE_ARG_RE.finditer(command)
    )
    return list(dict.fromkeys(captures))

