"""Classify a Bash command as a read-only orientation call.

Returns a short signature label, or ``None`` when the command is not a
known read. The session-cwd lint uses it to exempt read-shaped calls from
path authority checks; mutation analysis still applies.
"""

from __future__ import annotations

import re
import shlex
from typing import List, Mapping, Optional, Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse, ShellSegment, parse_shell
from yoke_core.domain.path_claim_bash_substitution import executable_substitutions
from yoke_core.domain.lint_session_cwd_git_read_forms import (
    GIT_MUTATING_SUBS,
    classify_git,
    git_subcommand,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    REDIRECT_OPERATORS,
    STDOUT_REPORTERS,
)


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
    return None


def _classify_service_client(args: List[str]) -> Optional[str]:
    """``service_client`` read-only subcommand list."""
    if not args:
        return None
    sub = args[0]
    if sub.endswith("-list") or sub.endswith("-get") or sub.endswith("-conflicts"):
        return f"service_client-{sub}"
    if sub == "session-checkpoint-read":
        return "service_client-session-checkpoint-read"
    return None


def _classify_harness_sessions(args: List[str]) -> Optional[str]:
    """``yoke_core.hooks.sessions_cli`` orientation reads."""
    if not args:
        return None
    if args[0] == "who-claims":
        return "harness_sessions-who-claims"
    if args[0] == "list":
        return "harness_sessions-list"
    return None


def git_write_targets(
    segment: str | ShellSegment,
    *,
    bindings: Optional[Mapping[str, str]] = None,
) -> Tuple[List[str], bool]:
    """Write paths for one git segment, plus unresolved-operand status."""
    from yoke_core.domain.lint_session_cwd_target_extract_shell import (
        resolve_operand_targets,
    )

    parsed = _single_segment(segment)
    if parsed is None or git_subcommand(list(parsed.argv)) not in GIT_MUTATING_SUBS:
        return [], False
    return resolve_operand_targets(parsed.text, bindings=bindings)


_SINGLE_ARG_READ_ONLY = frozenset({"wc", "ls", "cat", "head", "tail", "file", "stat"})


def _tokens_have_file_redirect(tokens: List[str]) -> bool:
    for tok in tokens:
        if tok in REDIRECT_OPERATORS:
            return True
        if tok.startswith(">") and not tok.startswith(">&"):
            return True
        if tok.startswith(("1>", "2>", "&>")) and ">&" not in tok:
            return True
    return False


def _classify_stdout_reporter(tokens: List[str]) -> Optional[str]:
    """``print`` / ``printf`` without a file redirect — stdout only."""
    if not tokens or tokens[0] not in STDOUT_REPORTERS:
        return None
    if _tokens_have_file_redirect(tokens):
        return None
    return f"{tokens[0]}-report"


def _classify_single_arg_read(tokens: List[str]) -> Optional[str]:
    """File readers. Extra paths are still reads; a redirect is a write."""
    if not tokens or tokens[0] not in _SINGLE_ARG_READ_ONLY:
        return None
    if _tokens_have_file_redirect(tokens):
        return None
    return f"{tokens[0]}-read"


def _classify_sed_read(tokens: List[str]) -> Optional[str]:
    """Accept only ``sed -n`` with a numeric print program and one path."""
    if len(tokens) == 4 and tokens[:2] == ["sed", "-n"]:
        if re.fullmatch(r"\d+(?:,\d+)?p", tokens[2]):
            return "sed-read"
    return None


_GREP_LIKE = frozenset({"grep", "rg", "ag", "ack"})


def _classify_grep_like(tokens: List[str]) -> Optional[str]:
    """``grep`` / ``rg`` calls are read-only by default."""
    if not tokens:
        return None
    if tokens[0] == "rg" and any(
        t == "--pre" or t.startswith("--pre=") for t in tokens[1:]
    ):
        return None
    if tokens[0] in _GREP_LIKE:
        return tokens[0]
    return None


_FIND_WRITES = frozenset({"-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})
_FIND_EXECS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


def _find_exec_commands(tokens: List[str]) -> Optional[List[List[str]]]:
    """Commands ``-exec`` and kin run, or ``None`` when one is unterminated."""
    commands: List[List[str]] = []
    i = 1
    while i < len(tokens):
        if tokens[i] not in _FIND_EXECS:
            i += 1
            continue
        start = end = i + 1
        while end < len(tokens) and not (
            tokens[end] == ";" or (tokens[end] == "+" and tokens[end - 1] == "{}")
        ):
            end += 1
        if end >= len(tokens) or end == start:
            return None
        commands.append(tokens[start:end])
        i = end + 1
    return commands


def _classify_find(tokens: List[str]) -> Optional[str]:
    """``find`` reads unless it writes a file or runs a command that is not a read."""
    if not tokens or tokens[0] != "find":
        return None
    if any(t in _FIND_WRITES for t in tokens[1:]):
        return None
    commands = _find_exec_commands(tokens)
    if commands is None or not all(_match_simple(shlex.join(c)) for c in commands):
        return None
    return "find"


def _classify_python_module(tokens: List[str]) -> Optional[str]:
    module = _module_name(tokens)
    if not module:
        return None
    args = _module_args(tokens)
    if module == "yoke_core.cli.db_router":
        return _classify_db_router(args)
    if module == "yoke_core.api.service_client":
        return _classify_service_client(args)
    if module == "yoke_core.hooks.sessions_cli":
        return _classify_harness_sessions(args)
    return None


# Env-prefix names that imply module-resolution override; their presence
# disqualifies the command from the read-only allow-path because the
# PYTHONPATH-equivalence rule (``lint_session_cwd_control_plane``) is the
# canonical surface for resolving such commands and it operates on the
# cwd-fallback branch.
_MODULE_RESOLUTION_ENV_PREFIXES = ("PYTHONPATH", "PYTHONHOME")


def _single_segment(segment: str | ShellSegment) -> Optional[ShellSegment]:
    """``segment`` as one parsed simple command, or ``None`` if it is not one."""
    if isinstance(segment, ShellSegment):
        return segment
    parsed = parse_shell(segment)
    if parsed.unparsed or len(parsed.segments) != 1:
        return None
    return parsed.segments[0]


_SIMPLE_CLASSIFIERS = (
    _classify_python_module,
    classify_git,
    _classify_grep_like,
    _classify_find,
    _classify_stdout_reporter,
    _classify_sed_read,
    _classify_single_arg_read,
)


def _match_simple(segment: str | ShellSegment) -> Optional[str]:
    """Signature label for one simple command; a module-resolution
    override (``PYTHONPATH``, ``PYTHONHOME``) refuses classification."""
    parsed = _single_segment(segment)
    if parsed is None or not parsed.argv or executable_substitutions(parsed.text)[1]:
        return None
    if any(
        parsed.assignment(name) is not None for name in _MODULE_RESOLUTION_ENV_PREFIXES
    ):
        return None
    tokens = list(parsed.argv)
    if tokens[0].rsplit("/", 1)[-1] == "git" and parsed.assignments:
        return None
    for classifier in _SIMPLE_CLASSIFIERS:
        label = classifier(tokens)
        if label:
            return label
    return None


def match_read_only_signature(command: str | ShellParse) -> Optional[str]:
    """Return a short signature label when ``command`` is read-only, else ``None``.

    A compound is read-only only when every segment matches on its own.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    segments = parsed.segments
    if parsed.unparsed or not segments:
        return None
    if len(segments) == 1:
        return _match_simple(segments[0])
    if all(_match_simple(segment) for segment in segments):
        return "compound-read"
    return None


__all__ = [
    "git_write_targets",
    "match_read_only_signature",
]
