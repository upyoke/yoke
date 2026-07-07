"""Classify a Bash command body as a read-only / self-orientation call.

The session-cwd lint denies tool calls whose target paths fall outside
the session's claim authority. When ``extract_payload_targets`` finds
no extractable target the lint historically fell back to denying based
on the harness cwd alone, which over-denies read-only orientation
calls (``db_router query``, ``service_client --help``,
``harness_sessions who-claims``, etc.) that touch no specific file.

This module is the single-responsibility classifier: given a Bash
command body, return the matched read-only signature (a short label) or
``None`` if the command does not match any read-only shape. The caller
(:mod:`lint_session_cwd`) short-circuits the cwd-fallback deny path and
emits ``SessionCwdMismatchAllowedReadOnly`` when a signature matches.

Adding a new signature here is the operator-facing extension point —
keep regexes tight and label them descriptively so the emitted event
carries actionable provenance.
"""

from __future__ import annotations

import re
import shlex
from typing import List, Optional


# Matched against the *first substantive token sequence* of the command.
# Each entry is ``(label, predicate)`` — predicate receives the tokenized
# argv minus leading env assignments. Order matters: the first match
# wins.
_PYTHON_RUN = ("python3", "-m")


def _is_python_module_call(tokens: List[str]) -> bool:
    return len(tokens) >= 3 and tokens[0:2] == list(_PYTHON_RUN)


def _module_name(tokens: List[str]) -> str:
    return tokens[2] if _is_python_module_call(tokens) else ""


def _module_args(tokens: List[str]) -> List[str]:
    return tokens[3:] if _is_python_module_call(tokens) else []


def _has_help_flag(args: List[str]) -> bool:
    return "--help" in args or "-h" in args


def _classify_db_router(args: List[str]) -> Optional[str]:
    """``db_router`` read-only subcommands only."""
    if not args:
        return None
    sub = args[0]
    rest = args[1:]
    if sub == "query":
        return "db_router-query"
    if sub == "events" and rest and rest[0] == "list":
        return "db_router-events-list"
    if sub == "path-claims" and rest and rest[0] == "list":
        return "db_router-path-claims-list"
    if sub == "harness-sessions" and rest and rest[0] == "who-claims":
        return "db_router-harness-sessions-who-claims"
    if sub == "items" and rest and rest[0] == "get":
        return "db_router-items-get"
    if sub == "sections" and rest and rest[0] == "get":
        return "db_router-sections-get"
    if _has_help_flag(args):
        return "db_router-help"
    return None


def _classify_service_client(args: List[str]) -> Optional[str]:
    """``service_client`` read-only subcommand list."""
    if not args:
        return None
    sub = args[0]
    if _has_help_flag(args):
        return "service_client-help"
    if sub.endswith("-list") or sub.endswith("-get") or sub.endswith("-conflicts"):
        return f"service_client-{sub}"
    if sub == "session-checkpoint-read":
        return "service_client-session-checkpoint-read"
    return None


def _classify_harness_sessions(args: List[str]) -> Optional[str]:
    """``runtime.harness.harness_sessions who-claims`` and ``--help``."""
    if not args:
        return None
    if _has_help_flag(args):
        return "harness_sessions-help"
    if args[0] == "who-claims":
        return "harness_sessions-who-claims"
    if args[0] == "list":
        return "harness_sessions-list"
    return None


def _git_has_target_flag(tokens: List[str]) -> bool:
    """Return True when the command names a target via -C / --git-dir / --work-tree."""
    for i, tok in enumerate(tokens):
        if tok in {"-C", "--git-dir", "--work-tree"}:
            return True
        if tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
            return True
    return False


_GIT_READ_ONLY_SUBS = frozenset({
    "status", "log", "diff", "show", "rev-parse", "branch", "remote",
    "config", "describe", "ls-files", "ls-tree", "blame", "shortlog",
})


def _classify_git(tokens: List[str]) -> Optional[str]:
    """``git <read-only-sub>`` with no target flag — orientation."""
    if not tokens or tokens[0] != "git":
        return None
    if _git_has_target_flag(tokens):
        return None
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        if tok in _GIT_READ_ONLY_SUBS:
            return f"git-{tok}"
        return None
    return None


_SINGLE_ARG_READ_ONLY = frozenset({"wc", "ls", "cat", "head", "tail", "file", "stat"})


def _classify_single_arg_read(tokens: List[str]) -> Optional[str]:
    """``wc -l <path>`` / ``ls <path>`` / ``cat <path>`` — single positional path."""
    if not tokens or tokens[0] not in _SINGLE_ARG_READ_ONLY:
        return None
    positional = [t for t in tokens[1:] if not t.startswith("-")]
    if len(positional) <= 1:
        return f"{tokens[0]}-read"
    return None


_GREP_LIKE = frozenset({"grep", "rg", "ag", "ack"})


def _classify_grep_like(tokens: List[str]) -> Optional[str]:
    """``grep`` / ``rg`` calls are read-only by default."""
    if not tokens:
        return None
    if tokens[0] in _GREP_LIKE:
        return tokens[0]
    return None


def _classify_python_module(tokens: List[str]) -> Optional[str]:
    module = _module_name(tokens)
    if not module:
        return None
    args = _module_args(tokens)
    if module == "yoke_core.cli.db_router":
        return _classify_db_router(args)
    if module == "yoke_core.api.service_client":
        return _classify_service_client(args)
    if module == "runtime.harness.harness_sessions":
        return _classify_harness_sessions(args)
    if _has_help_flag(args):
        return f"python-{module}-help"
    return None


# Env-prefix names that imply module-resolution override; their presence
# disqualifies the command from the read-only allow-path because the
# PYTHONPATH-equivalence rule (``lint_session_cwd_control_plane``) is the
# canonical surface for resolving such commands and it operates on the
# cwd-fallback branch.
_MODULE_RESOLUTION_ENV_PREFIXES = frozenset({"PYTHONPATH", "PYTHONHOME"})


def _strip_env_prefixes(tokens: List[str]) -> Optional[List[str]]:
    """Strip ``FOO=bar`` env prefix tokens; return ``None`` when a
    module-resolution override (``PYTHONPATH``, ``PYTHONHOME``) is
    present so the caller refuses to classify the command as read-only.
    """
    out = list(tokens)
    while out and "=" in out[0] and not out[0].startswith("-"):
        head = out[0].split("=", 1)[0]
        if head and head.replace("_", "").isalnum() and head[0].isalpha():
            if head in _MODULE_RESOLUTION_ENV_PREFIXES:
                return None
            out = out[1:]
            continue
        break
    return out


_COMPOUND_RE = re.compile(r"[;&|]")


def _has_compound_separator(command: str) -> bool:
    return bool(_COMPOUND_RE.search(command))


def match_read_only_signature(command: str) -> Optional[str]:
    """Return a short signature label when ``command`` is read-only, else ``None``.

    Compound commands (``;``, ``&&``, ``||``, ``|``) are never classified
    as pure read-only — the second clause could mutate, and we are
    conservative on the allow-path.
    """
    if not command or not command.strip():
        return None
    if _has_compound_separator(command):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    tokens = _strip_env_prefixes(tokens)
    if tokens is None or not tokens:
        return None
    for classifier in (
        _classify_python_module,
        _classify_git,
        _classify_grep_like,
        _classify_single_arg_read,
    ):
        label = classifier(tokens)
        if label:
            return label
    return None


__all__ = ["match_read_only_signature"]
