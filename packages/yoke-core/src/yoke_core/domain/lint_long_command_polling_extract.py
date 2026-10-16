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
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence

from yoke_core.domain.lint_long_command_polling_constants import (
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
    SUPPRESSION_TOKEN,
)
from yoke_core.domain.lint_command_extract import (  # noqa: F401
    extract_command as _extract_command,
)


#: Matches nothing: with no client scratch roots no path counts as a capture.
_NO_ROOT = "(?!)"

# Peek verbs: any reading verb against a capture file is a peek (audit
# evidence showed `grep`/`wc`/`ls`/`awk`/`sed`/`stat` etc. were used to
# peek unblocked). `[^;&]*?` (no pipe exclusion) so `grep -E "p|f" path`
# still matches. `(?<![-/=])` rejects `--body-file /tmp/x` shapes.
PEEK_VERB_ALT = (
    "tail|head|cat|wc|grep|egrep|fgrep|rg|ls|awk|sed|less|more|file|stat|"
    "nl|cut|sort|uniq"
)
# Watcher-arg flag names are unique to our wrappers — the flag IS the
# discriminator, so the path argument can live in any tempdir.
_WATCHER_CAPTURE_ARG_RE = re.compile(
    r"--(?:raw-capture|progress-capture)(?:=|\s+)([^\s;&|<>]+)",
)
_SLEEP_THEN_PEEK_RE = re.compile(
    rf"\bsleep\s+(\d+)\s*(?:&&|;)\s*(?<![-/=])(?:{PEEK_VERB_ALT})\b",
)
# Monitor command: the watcher follower in either spelling (`yoke watch
# tail`, or the module fallback) or bare `tail -f/-F`, against a capture
# file. Trailing filters (`| grep ...`) are intentionally ignored —
# capture-file equivalence is what matters.
_WATCH_TAIL_ALTERNATION = (
    r"yoke\s+watch\s+tail"
    r"|python3\s+-m\s+(?:yoke_core|runtime\.api)\.tools\.watch_tail"
)


def capture_path_group(roots: Sequence[str]) -> str:
    """Return the regex matching a path under one of *roots*.

    *roots* are the client machine's scratch roots
    (:func:`yoke_contracts.hook_runner.client_facts.capture_roots`). The
    authority never substitutes its own: a capture lives where the client
    wrote it.
    """
    alternation = "|".join(re.escape(r.rstrip("/")) for r in roots if r)
    return f"(?:{alternation or _NO_ROOT})/[\\w./-]+"


@dataclass(frozen=True)
class CapturePatterns:
    """Capture-path patterns compiled for one set of client scratch roots."""

    peek_verb: re.Pattern[str]
    redirect: re.Pattern[str]
    monitor: re.Pattern[str]


@lru_cache(maxsize=32)
def capture_patterns(roots: tuple[str, ...]) -> CapturePatterns:
    path = capture_path_group(roots)
    return CapturePatterns(
        peek_verb=re.compile(rf"(?<![-/=])\b({PEEK_VERB_ALT})\b[^;&]*?({path})"),
        redirect=re.compile(rf">>?\s*({path})"),
        monitor=re.compile(
            rf"\b(?:{_WATCH_TAIL_ALTERNATION}|tail\s+-[FfnvqzN]+)\s+({path})",
        ),
    )


def _extract_tool_input(payload: dict) -> dict:
    """Return ``tool_input`` accepting any of the known payload shapes."""
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


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


_PEEK_VERBS = frozenset(
    {
        "tail",
        "head",
        "cat",
        "wc",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ls",
        "awk",
        "sed",
        "less",
        "more",
        "file",
        "stat",
        "nl",
        "cut",
        "sort",
        "uniq",
    }
)


def _is_stdin_feed_cat(command: str, match) -> bool:
    """True iff matched ``cat <tmpfile>`` is feeding stdin downstream.

    ``cat <tmpfile> | <substantive consumer>`` is a stdin feed (tempfile
    is content payload), not a polling peek. Restricted to ``cat``;
    pipelines of peek verbs (``cat | tail``) stay peeks.
    """
    if match.group(1) != "cat":
        return False
    tail = command[match.end() :].lstrip()
    if not tail.startswith("|") or tail.startswith("||"):
        return False
    after_pipe = tail[1:].lstrip()
    if not after_pipe:
        return False
    consumer = after_pipe.split(None, 1)[0].rsplit("/", 1)[-1]
    return consumer not in _PEEK_VERBS


def _extract_peek_capture_file(command: str, roots: Sequence[str]) -> Optional[str]:
    """Return the /tmp capture-file path if *command* looks like a peek.

    Any reading verb in :data:`PEEK_VERB_ALT` against a path under one of
    the client's scratch *roots* is a peek. Carve-out: ``cat <tmpfile> | <substantive consumer>``
    is a stdin feed (see :func:`_is_stdin_feed_cat`).
    """
    patterns = capture_patterns(tuple(roots))
    m = patterns.peek_verb.search(command)
    if not m:
        return None
    if patterns.redirect.search(command):
        return None
    if _is_stdin_feed_cat(command, m):
        return None
    return m.group(2)


def _peek_read_in_command_substitution(command: str, roots: Sequence[str]) -> bool:
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
    m = capture_patterns(tuple(roots)).peek_verb.search(command)
    if not m:
        return False
    prefix = command[: m.start()]
    open_idx = prefix.rfind("$(")
    # Enclosed iff a `$(` opens before the verb with no `)` in between
    # (a closed earlier substitution does not enclose the read).
    return open_idx != -1 and ")" not in prefix[open_idx + 2 :]


def _extract_sleep_cadence(command: str) -> Optional[int]:
    """Return the ``sleep N`` seconds value before a tail/head/cat, if present."""
    m = _SLEEP_THEN_PEEK_RE.search(command)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _extract_monitor_capture_file(command: str, roots: Sequence[str]) -> Optional[str]:
    """Return the capture-file path a Monitor command targets, if any.

    Accepts the follower in either spelling (``yoke watch tail
    <path>`` or the ``python3 -m yoke_core.tools.watch_tail <path>``
    fallback) and the bare ``tail -f <path>`` shape (including ``-F`` /
    additional flags). The
    trailing pipeline (``| grep --line-buffered ...``) is intentionally
    NOT inspected: two Monitors against the same capture file are
    duplicates even when their filter expressions differ. Returns
    ``None`` when *command* does not match either shape
    or does not reference a tempdir path.
    """
    match = capture_patterns(tuple(roots)).monitor.search(command)
    if not match:
        return None
    return match.group(1)


def _extract_background_capture_files(command: str, roots: Sequence[str]) -> list[str]:
    """Return capture files that indicate a long background command is active."""
    captures: list[str] = []
    redirect = capture_patterns(tuple(roots)).redirect.search(command)
    if redirect:
        captures.append(redirect.group(1))
    captures.extend(
        match.group(1) for match in _WATCHER_CAPTURE_ARG_RE.finditer(command)
    )
    return list(dict.fromkeys(captures))
