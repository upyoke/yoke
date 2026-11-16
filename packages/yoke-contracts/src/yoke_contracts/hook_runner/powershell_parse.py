"""PowerShell tokenizer producing the same :class:`ShellParse` the Bash guards read.

Guards ask one question of a command — which programs run, with which
words, in which directory — so a PowerShell command yields the same
segments a Bash command would:

- Here-strings (``@'...'@``, ``@"..."@``) are input, not commands. They are
  lifted out first, kept on ``ShellParse.heredocs`` (``expands`` for the
  double-quoted form) and left in the code as an empty ``''`` argument.
- ``#`` comments and ``<# ... #>`` blocks are dropped.
- Statements split on unquoted ``;``, newlines, ``&&``, ``||``, a trailing
  background ``&`` and a top-level ``{`` or ``}``, so the body of
  ``if (...) { git commit }`` or ``ForEach-Object { Remove-Item $_ }`` is its
  own segment. Pipelines split on ``|``. Anything inside ``(...)``,
  ``$(...)``, ``@(...)``, ``@{...}`` or ``${...}`` stays one word, as a Bash
  substitution does. A backtick escapes the next character; backtick-newline
  continues the line.
- Each segment's ``argv`` drops the call operator (``&``) or dot-source
  (``.``). A control keyword (``if``, ``foreach``, ``while``...) leaves no
  argv. ``$name = value`` (or ``$env:NAME = value``) records ``name=value``
  as an assignment when the right side is a value; when it is a command
  (``$sha = git rev-parse HEAD``) that command is the argv.
- ``ShellSegment.program`` is lowercased, without directories or ``.exe``,
  because Windows command lookup ignores case.
"""

from __future__ import annotations

import re

from yoke_contracts.hook_runner.shell_expansion_scan import Heredoc
from yoke_contracts.hook_runner.shell_parse import ShellParse, ShellSegment
from yoke_contracts.hook_runner.shell_word import ShellWord

POWERSHELL = "powershell"

CONTROL_KEYWORDS = frozenset(
    {
        "begin", "break", "catch", "class", "continue", "data", "do",
        "dynamicparam", "else", "elseif", "end", "enum", "exit", "filter",
        "finally", "for", "foreach", "function", "if", "param", "process",
        "return", "switch", "throw", "trap", "try", "until", "while",
    }
)
_ASSIGNMENT = re.compile(r"^\$(?:env:)?([A-Za-z_][A-Za-z0-9_]*)$", re.IGNORECASE)
_ASSIGN_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "??="})
_HERE_OPEN = re.compile(r"@(['\"])[ \t]*\r?\n")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}
_OPENERS = {"$(": ")", "@(": ")", "@{": "}", "${": "}"}


def _lift_here_strings(text: str) -> tuple[str, tuple[Heredoc, ...]]:
    code: list[str] = []
    heredocs: list[Heredoc] = []
    cursor = 0
    for match in _HERE_OPEN.finditer(text):
        if match.start() < cursor or _in_quote(text, cursor, match.start()):
            continue
        quote = match.group(1)
        close = re.compile(r"^" + re.escape(quote) + "@", re.MULTILINE)
        end = close.search(text, match.end())
        if end is None:
            continue
        code.append(text[cursor:match.start()])
        offset = sum(len(part) for part in code)
        code.append("''")
        body_end = end.start() - 1 if end.start() > match.end() else end.start()
        heredocs.append(
            Heredoc(
                operator_offset=offset,
                delimiter=quote + "@",
                expands=quote == '"',
                body=text[match.end():max(body_end, match.end())],
                source_operator_start=match.start(),
                source_operator_end=match.end(),
                source_body_start=match.end(),
                source_body_end=end.end(),
            )
        )
        cursor = end.end()
    code.append(text[cursor:])
    return "".join(code), tuple(heredocs)


def _in_quote(text: str, start: int, stop: int) -> bool:
    quote = ""
    for ch in text[start:stop]:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
    return bool(quote)


def _skip_quoted(code: str, i: int) -> int:
    """Index just past the quoted string opening at ``i``; raise if unclosed."""
    quote = code[i]
    i += 1
    while i < len(code):
        ch = code[i]
        if quote == '"' and ch == "`":
            i += 2
            continue
        if quote == '"' and code.startswith("$(", i):
            i = _skip_nested(code, i + 2, ")")
            continue
        if ch == quote:
            if code.startswith(quote * 2, i):
                i += 2
                continue
            return i + 1
        i += 1
    raise ValueError("unterminated quote")


def _skip_nested(code: str, i: int, closer: str) -> int:
    """Index just past ``closer`` for a group whose body starts at ``i``."""
    while i < len(code):
        ch = code[i]
        if ch == "`":
            i += 2
        elif ch in "'\"":
            i = _skip_quoted(code, i)
        elif ch == closer:
            return i + 1
        elif ch == "(":
            i = _skip_nested(code, i + 1, ")")
        elif ch == "{":
            i = _skip_nested(code, i + 1, "}")
        else:
            i += 1
    raise ValueError(f"unclosed {closer!r}")


def _split(code: str) -> list[list[str]]:
    """Statements, each a list of pipeline-stage texts."""
    groups: list[list[str]] = []
    stages: list[str] = []
    current: list[str] = []

    def end_stage() -> None:
        text = "".join(current).strip()
        current.clear()
        if text:
            stages.append(text)

    def end_statement() -> None:
        end_stage()
        if stages:
            groups.append(list(stages))
            stages.clear()

    i = 0
    while i < len(code):
        ch = code[i]
        pending = "".join(current)
        at_word_start = not pending or pending[-1].isspace()
        if ch == "`":
            nxt = code[i + 1:i + 2]
            current.append(" " if nxt in ("\n", "\r") else code[i:i + 2])
            i += 3 if code.startswith("\r\n", i + 1) else 2
        elif code.startswith("<#", i):
            end = code.find("#>", i + 2)
            i = len(code) if end < 0 else end + 2
        elif ch == "#" and at_word_start:
            end = code.find("\n", i)
            i = len(code) if end < 0 else end
        elif ch in "'\"":
            end = _safe(_skip_quoted, code, i)
            current.append(code[i:end])
            i = end
        elif code[i:i + 2] in _OPENERS or ch == "(":
            width = 2 if code[i:i + 2] in _OPENERS else 1
            end = _safe(_skip_nested, code, i + width, _OPENERS.get(code[i:i + 2], ")"))
            current.append(code[i:end])
            i = end
        elif code.startswith("&&", i) or code.startswith("||", i) or ch in ";\n{}":
            end_statement()
            i += 2 if code[i:i + 2] in ("&&", "||") else 1
        elif ch == "|":
            end_stage()
            i += 1
        elif ch == "&" and pending.rstrip() and not pending.rstrip().endswith(">"):
            end_statement()
            i += 1
        else:
            current.append(ch)
            i += 1
    end_statement()
    return groups


def _safe(func, code: str, *args) -> int:
    """Run a skip helper; an unclosed group swallows the rest of the text."""
    try:
        return func(code, *args)
    except ValueError:
        return len(code)


def _words(stage: str) -> list[str]:
    """Split one stage into words, removing quotes; raise on unbalanced text."""
    words: list[str] = []
    word: list[str] = []
    started = False
    i = 0
    while i < len(stage):
        ch = stage[i]
        if ch.isspace():
            if started:
                words.append(ShellWord("".join(word), 0))
                word.clear()
                started = False
            i += 1
            continue
        started = True
        if ch == "`" and i + 1 < len(stage):
            word.append(_ESCAPES.get(stage[i + 1], stage[i + 1]))
            i += 2
        elif ch == "'":
            end = _skip_quoted(stage, i)
            word.append(stage[i + 1:end - 1].replace("''", "'"))
            i = end
        elif ch == '"':
            end = _skip_quoted(stage, i)
            word.append(_unescape_double(stage[i + 1:end - 1]))
            i = end
        elif stage[i:i + 2] in _OPENERS or ch == "(":
            width = 2 if stage[i:i + 2] in _OPENERS else 1
            end = _skip_nested(stage, i + width, _OPENERS.get(stage[i:i + 2], ")"))
            word.append(stage[i:end])
            i = end
        else:
            word.append(ch)
            i += 1
    if started:
        words.append(ShellWord("".join(word), 0))
    return words


def _unescape_double(body: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "`" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        elif body.startswith('""', i):
            out.append('"')
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _segment(text: str, tokens: list[str], pipeline: int, stage: int) -> ShellSegment:
    index = 0
    if tokens and tokens[0].lower() in CONTROL_KEYWORDS:
        return ShellSegment(text, tuple(tokens), (), (), pipeline, stage, POWERSHELL)
    assignments: list[str] = []
    while index + 1 < len(tokens) and tokens[index + 1] in _ASSIGN_OPS:
        target = _ASSIGNMENT.match(tokens[index])
        if target is None:
            break
        index += 2
        rhs = text.split(tokens[index - 1], 1)[-1].lstrip()
        if not rhs or rhs[0] in "'\"$(@[0123456789-":
            value = tokens[index] if index < len(tokens) else ""
            assignments.append(f"{target.group(1)}={value}")
            return ShellSegment(
                text, tuple(tokens), tuple(assignments), (), pipeline, stage, POWERSHELL
            )
    if index < len(tokens) and tokens[index] in ("&", "."):
        index += 1
    return ShellSegment(
        text, tuple(tokens), tuple(assignments), tuple(tokens[index:]), pipeline, stage,
        POWERSHELL,
    )


def parse_powershell(command: str) -> ShellParse:
    """Parse a PowerShell ``command`` once for every guard; never raises."""
    text = command or ""
    code, heredocs = _lift_here_strings(text)
    segments: list[ShellSegment] = []
    unparsed: list[str] = []
    for pipeline, stages in enumerate(_split(code)):
        for stage, statement in enumerate(stages):
            try:
                tokens = _words(statement)
            except ValueError:
                unparsed.append(statement)
                continue
            if tokens:
                segments.append(_segment(statement, tokens, pipeline, stage))
    return ShellParse(
        text, code, heredocs, tuple(segments), tuple(unparsed), POWERSHELL
    )


__all__ = ["CONTROL_KEYWORDS", "POWERSHELL", "parse_powershell"]
