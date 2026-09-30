"""Ask an adapter's parser about a taught recipe, without running it.

``product_boundary_teaching`` already resolves every taught ``yoke``
spelling against the registered command set. What it cannot judge on its
own is the argument shape of a recipe written with documentation
placeholders — ``{project}``, ``<requirement-id>``, ``$_item_project``,
``PREFIX-N`` — which is most of them, and exactly where a flag the CLI no
longer carries hides.

This module is the ``SmokeRunner`` that closes that half. It substitutes
each placeholder with a concrete stand-in and asks the resolved adapter's
argument parser whether it accepts the literal. Only the parser's verdict
is read, and the probe unwinds the moment that verdict exists: a
registered command can install a Pack, sync a snapshot, or open a
database, and a check that reads documentation has no business doing any
of those.
"""

from __future__ import annotations

import argparse
import io
import re
import shlex
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Iterator, List, Optional, Sequence, Tuple

from yoke_cli.commands.registry import resolve
from yoke_contracts.items_projection import ALLOWED_GET_FIELDS, unknown_field_message


# A shell operator ends the yoke invocation; everything past it belongs to
# another process. A heredoc redirect names a body the recipe supplies on
# stdin, which the parser never sees. Command substitution is collapsed
# first so its own pipes cannot be mistaken for the end of the command.
# A rendered agent body escapes its line continuations, so the joined
# line arrives carrying the backslash itself. Left in place, shlex reads
# it as escaping the next flag and the argv silently loses a token.
_CONTINUATION_RE = re.compile(r"\\{1,2}\s+")
_COMMAND_SUBSTITUTION_RE = re.compile(r"\$\((?:[^()]|\([^()]*\))*\)")
_TRAILING_SHELL_RE = re.compile(r"\s(?:\|\||\||&&|;|>>?|2>&1|<<[-']?\s*\S+).*$")
_HEREDOC_RE = re.compile(r"<<-?['\"]?\w+['\"]?")
# Placeholder notations the teaching trees use. ``[...]`` is grammar
# rather than a value — an optional group in a usage line — so it is
# dropped whole.
_PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}|<[^<>]+>|\$\{[^}]+\}|\$[A-Za-z_]\w*")
_OPTIONAL_GROUP_RE = re.compile(r"\[[^\[\]]*\]")
_DOC_REF_RE = re.compile(r"\b(?:PREFIX|YOK|QUALIFIED-ITEM)-N\b")
# A numeric stand-in is required wherever the placeholder names a count,
# an id, or a duration; argparse rejects text for those.
_NUMERIC_HINT_RE = re.compile(
    r"^n$|id$|_id|num|count|sec|second|minute|timeout|tokens|port|cap|size"
    r"|lines|index|step|attempt|limit|budget|samples|width|window|days",
    re.IGNORECASE,
)
_INVALID_CHOICE_RE = re.compile(r"invalid choice: '([^']*)' \(choose from ([^)]*)\)")
_TEXT_STANDIN = "PLACEHOLDER"
_REF_STANDIN = "YOK-1"
_STANDINS = (_TEXT_STANDIN, _REF_STANDIN, "1")


def _standin(body: str) -> str:
    inner = body.strip("{}<>$ ").strip("'\"")
    if "|" in inner:
        # ``<failed|new|unclear>`` names the allowed values inline; the
        # first alternative is the one concrete value the notation offers.
        return inner.split("|", 1)[0].strip()
    if _NUMERIC_HINT_RE.search(inner):
        return "1"
    return _TEXT_STANDIN


def normalize(recipe: str, *, numeric: bool = False) -> str:
    """Return *recipe* with shell composition and placeholders removed.

    ``numeric`` substitutes every placeholder with ``1`` instead of
    choosing per placeholder; a recipe the parser accepts under either
    profile satisfies the contract, so a doc-shaped value name never
    reads as a defect.
    """
    text = _CONTINUATION_RE.sub(" ", recipe)
    text = _COMMAND_SUBSTITUTION_RE.sub(_TEXT_STANDIN, text)
    text = _HEREDOC_RE.sub("", _TRAILING_SHELL_RE.sub("", text)).strip()
    text = _DOC_REF_RE.sub(_REF_STANDIN, text)
    text = _OPTIONAL_GROUP_RE.sub(" ", text)
    if numeric:
        text = _PLACEHOLDER_RE.sub("1", text)
    else:
        text = _PLACEHOLDER_RE.sub(lambda m: _standin(m.group(0)), text)
    return " ".join(text.split())


def _tokens(recipe: str) -> Optional[List[str]]:
    argv = None
    # A doc wraps a long JSON value across lines, which leaves the quote
    # open on the extracted line. Closing it keeps the value one token,
    # and the flags around it are what this probe reads.
    for suffix in ("", '"', "'"):
        try:
            argv = shlex.split(recipe + suffix)
            break
        except ValueError:
            continue
    if not argv or argv[0] != "yoke":
        return None
    if len(argv) > 1 and argv[1] in _STANDINS:
        # ``yoke <subcommand> [args...]`` is grammar, not a recipe.
        return None
    return argv


def _global_flags_stripped(argv: Sequence[str]) -> List[str]:
    out: List[str] = []
    skip = False
    for token in argv:
        if skip:
            skip = False
            continue
        if token == "--env":
            skip = True
            continue
        if token.startswith("--env="):
            continue
        out.append(token)
    return out


class _ParsedOK(Exception):
    """Raised the moment an adapter's parser accepts the literal."""


class _ProjectionError(Exception):
    """A parsed item read names a field the shared projection refuses."""


def _check_projection(
    parser: argparse.ArgumentParser, parsed: argparse.Namespace
) -> None:
    if parser.prog != "yoke items get":
        return
    for field in parsed.fields:
        if field not in ALLOWED_GET_FIELDS and field not in _STANDINS:
            raise _ProjectionError(unknown_field_message(field))


@contextmanager
def _abort_after_parse() -> Iterator[None]:
    real_parse = argparse.ArgumentParser.parse_args
    real_known = argparse.ArgumentParser.parse_known_args

    def parse_args(self, args=None, namespace=None):
        parsed = real_parse(self, args, namespace)
        _check_projection(self, parsed)
        raise _ParsedOK()

    def parse_known_args(self, args=None, namespace=None):
        parsed, _remaining = real_known(self, args, namespace)
        _check_projection(self, parsed)
        raise _ParsedOK()

    argparse.ArgumentParser.parse_args = parse_args
    argparse.ArgumentParser.parse_known_args = parse_known_args
    try:
        yield
    finally:
        argparse.ArgumentParser.parse_args = real_parse
        argparse.ArgumentParser.parse_known_args = real_known


def _usage_error(command_argv: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(function_id, usage_detail)`` for one parse attempt."""
    try:
        _route, function_id, adapter, rest = resolve(command_argv)
    except KeyError:
        return None, None
    err = io.StringIO()
    try:
        with _abort_after_parse():
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = adapter(rest)
    except _ParsedOK:
        return function_id, None
    except _ProjectionError as exc:
        return function_id, str(exc)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 0
    except KeyboardInterrupt:
        raise
    except BaseException:
        # The adapter refused before it parsed, for a reason this probe
        # does not own — a missing connection, an unreadable checkout.
        return function_id, None
    if rc != 2:
        return function_id, None
    return function_id, _first_usage_line(err.getvalue())


def _first_usage_line(captured: str) -> str:
    for line in captured.splitlines():
        if ": error: " in line:
            return line.split(": error: ", 1)[1].strip()
    for line in captured.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("usage:"):
            continue
        if stripped.startswith("yoke ") or stripped.startswith("["):
            continue
        return stripped
    return "adapter rejected the arguments with usage exit 2"


def _repaired_choice(command_argv: List[str], detail: str) -> Optional[List[str]]:
    """Return *command_argv* with a rejected placeholder set to a real choice.

    A documentation placeholder cannot satisfy a declared choice set, and
    the parser names the set it wants. Substituting its first value asks
    the question this probe actually owns: does the flag exist, and does
    the recipe spell it correctly.

    Only a stand-in is repaired. A recipe that names a real value the
    parser rejects is teaching a value the CLI does not accept, which is
    the finding — not something to paper over.
    """
    match = _INVALID_CHOICE_RE.search(detail)
    if match is None:
        return None
    rejected = match.group(1)
    if rejected not in _STANDINS or rejected not in command_argv:
        return None
    offered = [c.strip().strip("'\"") for c in match.group(2).split(",")]
    if not offered or not offered[0]:
        return None
    return [offered[0] if token == rejected else token for token in command_argv]


def parse_probe(recipe: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Return ``(ok, function_id, error)`` for one taught recipe.

    Matches the ``SmokeRunner`` contract ``product_boundary_teaching``
    calls, so a rejected argument shape lands as ordinary
    ``stale_argument_shape`` drift beside the resolution findings.
    """
    verdict: Tuple[bool, Optional[str], Optional[str]] = (True, None, None)
    for numeric in (False, True):
        command_argv = _tokens(normalize(recipe, numeric=numeric))
        if command_argv is None:
            return True, None, None
        command_argv = _global_flags_stripped(command_argv[1:])
        function_id, detail = _usage_error(command_argv)
        for _attempt in range(len(command_argv)):
            if detail is None:
                break
            repaired = _repaired_choice(command_argv, detail)
            if repaired is None:
                break
            command_argv = repaired
            function_id, detail = _usage_error(command_argv)
        if detail is None:
            return True, function_id, None
        verdict = (False, function_id, detail)
    return verdict


__all__ = ["normalize", "parse_probe"]
