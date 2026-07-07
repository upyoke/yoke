"""Preprocessing fragment for HOOK_POLICY_SOURCE.

Holds RULE_TEXT_PREPROCESS — the imports, payload parsing, heredoc body
stripping helpers (iter_heredocs, segment_uses_python, ...), inline-Python
literal-DB block, and the quoted-string interior stripping. This is the
prelude every check fragment relies on; concatenated first into
HOOK_POLICY_SOURCE by lint_db_rules.
"""

from __future__ import annotations

RULE_TEXT_PREPROCESS = r"""
import sys
import json
import re
import os
import sqlite3
import ast
import shlex

try:
    data = json.load(sys.stdin)
except Exception as exc:
    print("lint-db-cmd: WARN invalid PreToolUse payload: %s" % exc, file=sys.stderr)
    sys.exit(0)

# Claude payload shape is usually:
#   {"tool_name":"Bash","tool_input":{"command":"..."}}
# But subagent payloads may vary by SDK/runtime version. Try known variants
# before treating the command as missing.
tool_input = data.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = data.get("toolInput")
if not isinstance(tool_input, dict):
    tool_input = data.get("input")
if not isinstance(tool_input, dict):
    tool_input = {}

command = tool_input.get("command")
if not isinstance(command, str) or command == "":
    if isinstance(tool_input.get("cmd"), str):
        command = tool_input.get("cmd")
    elif isinstance(data.get("command"), str):
        command = data.get("command")
    else:
        command = ""

if command == "":
    print("lint-db-cmd: WARN PreToolUse payload missing command field (allowing by default)", file=sys.stderr)
    sys.exit(0)

original_command = command

# --- Preprocessing: Strip heredoc bodies ---
# Heredoc body content (between <<DELIM ... DELIM) can contain references to
# guarded scripts, sqlite3, YOKE_SKILL_CONTEXT, etc. as prose, examples,
# or non-shell code (e.g., Python import sqlite3). These are not shell
# invocations and must not trigger any check. The one exception is executed
# Python payloads that call sqlite3.connect with a hardcoded Yoke DB path:
# those are inspected before stripping and denied below.
# Covers: <<EOF, << plus quoted-EOF, <<"EOF", <<-EOF (tab-stripping variant),
# tab-indented closing delimiters for <<-, and opener lines with trailing shell
# syntax (pipes, redirects, comments).
# The replacement preserves the heredoc opener AND any same-line suffix so the
# shell command structure remains intact for segment splitting and later checks
# can still see pipeline/redirect commands on the opener line.
# Note: cannot use literal single quotes inside python3 -c string,
# so build the regex with chr(39) for the single-quote character.
_sq = chr(39)
_heredoc_start_re = re.compile(
    r"(?P<prefix><<(?P<dash>-?)[ \t]*)["
    + _sq
    + r"\"]?(?P<delim>\w+)["
    + _sq
    + r"\"]?(?P<suffix>[^\n]*\n)"
)

def iter_heredocs(text):
    pos = 0
    while True:
        opener = _heredoc_start_re.search(text, pos)
        if opener is None:
            return

        close_pat = re.compile(
            r"(?m)^"
            + (r"\t*" if opener.group("dash") == "-" else "")
            + re.escape(opener.group("delim"))
            + r"\b"
        )
        closer = close_pat.search(text, opener.end())
        if closer is None:
            return

        yield opener, text[opener.end():closer.start()]
        pos = closer.end()

def segment_uses_python(segment):
    segment = segment.strip()
    if not segment:
        return False
    try:
        words = shlex.split(segment, posix=True)
    except Exception:
        words = segment.split()
    idx = 0
    while idx < len(words) and re.match(r"[A-Za-z_]\w*=.*", words[idx]):
        idx += 1
    if idx >= len(words):
        return False
    cmd_word = words[idx].rsplit("/", 1)[-1]
    if cmd_word in ("python", "python3"):
        return True
    if cmd_word == "uv" and idx + 2 < len(words) and words[idx + 1] == "run":
        nested = words[idx + 2].rsplit("/", 1)[-1]
        return nested in ("python", "python3")
    return False

def node_contains_yoke_db_literal(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "yoke.db" in sub.value:
            return True
    return False

def assigned_names_with_yoke_db(tree):
    names = set()
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Assign) and node_contains_yoke_db_literal(sub.value):
            for target in sub.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif (
            isinstance(sub, ast.AnnAssign)
            and isinstance(sub.target, ast.Name)
            and sub.value is not None
            and node_contains_yoke_db_literal(sub.value)
        ):
            names.add(sub.target.id)
    return names

def is_connect_call(func):
    if isinstance(func, ast.Attribute):
        return (
            isinstance(func.value, ast.Name)
            and func.value.id == "sqlite3"
            and func.attr == "connect"
        )
    return isinstance(func, ast.Name) and func.id == "connect"

def python_uses_literal_yoke_db(py_code):
    if "connect" not in py_code or "yoke.db" not in py_code:
        return False

    try:
        tree = ast.parse(py_code)
    except SyntaxError:
        tree = None

    if tree is not None:
        literal_names = assigned_names_with_yoke_db(tree)
        for sub in ast.walk(tree):
            if not isinstance(sub, ast.Call) or not is_connect_call(sub.func) or not sub.args:
                continue
            first_arg = sub.args[0]
            if node_contains_yoke_db_literal(first_arg):
                return True
            if isinstance(first_arg, ast.Name) and first_arg.id in literal_names:
                return True

    _dq = chr(34)
    _string_token = r"(?:[" + _sq + _dq + r"])(?:[^" + _sq + _dq + r"]*yoke\.db[^" + _sq + _dq + r"]*)(?:[" + _sq + _dq + r"])"
    return re.search(r"\bconnect\s*\([^)]*" + _string_token, py_code, flags=re.S) is not None

def extract_python_payloads(text):
    payloads = []
    for opener, body in iter_heredocs(text):
        line_start = text.rfind("\n", 0, opener.start()) + 1
        opener_line = text[line_start:opener.end()]
        if segment_uses_python(opener_line):
            payloads.append(body)

    _dq = chr(34)
    inline_python_re = re.compile(
        r"(?ms)(^|[;&|]\s*|\$\()\s*(?:[A-Za-z_]\w*=\S+\s+)*(?:python|python3|uv\s+run\s+python|uv\s+run\s+python3)\b[^\n]*?\s-c\s+(?P<quote>["
        + _sq
        + _dq
        + r"])(?P<code>(?:\\.|(?!(?P=quote)).)*)(?P=quote)"
    )
    for match in inline_python_re.finditer(text):
        payloads.append(match.group("code"))
    return payloads

def uses_raw_query_escape_hatch(text):
    if "yoke-" "db.sh" in text and "query" in text:
        return True
    return "yoke_core.cli.raw_query" in text


def extract_yoke_query_sql_payloads(text):
    payloads = []
    try:
        words = shlex.split(text, posix=True)
    except Exception:
        return payloads

    idx = 0
    while idx < len(words):
        if not re.search(r"(?:^|/)yoke-db\.sh$", words[idx]):
            idx += 1
            continue

        query_idx = idx + 1
        if query_idx >= len(words) or words[query_idx] != "query":
            idx += 1
            continue

        sql_idx = query_idx + 1
        if sql_idx < len(words) and words[sql_idx] == "-separator":
            sql_idx += 2

        if sql_idx < len(words):
            payloads.append(words[sql_idx])
        idx += 1
        continue

    idx = 0
    while idx < len(words):
        _word = words[idx].rsplit("/", 1)[-1]

        if (
            _word in ("python", "python3")
            and idx + 2 < len(words)
            and words[idx + 1] == "-m"
            and words[idx + 2] == "yoke_core.cli.raw_query"
        ):
            sql_idx = idx + 3
            if sql_idx < len(words) and words[sql_idx] == "-separator":
                sql_idx += 2
            if sql_idx < len(words):
                payloads.append(words[sql_idx])
            idx += 1
            continue

        if (
            _word == "uv"
            and idx + 4 < len(words)
            and words[idx + 1] == "run"
            and words[idx + 2].rsplit("/", 1)[-1] in ("python", "python3")
            and words[idx + 3] == "-m"
            and words[idx + 4] == "yoke_core.cli.raw_query"
        ):
            sql_idx = idx + 5
            if sql_idx < len(words) and words[sql_idx] == "-separator":
                sql_idx += 2
            if sql_idx < len(words):
                payloads.append(words[sql_idx])
        idx += 1

    return payloads

for py_code in extract_python_payloads(original_command):
    if python_uses_literal_yoke_db(py_code):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: Do not open the Yoke DB from ad-hoc Python using a hardcoded or relative "
                    "path like yoke.db. Use the canonical DB router / Postgres authority instead:\n"
                    "Examples:\n"
                    "  python3 -m yoke_core.cli.db_router query \"SELECT ...\"\n"
                    "  python3 -m yoke_core.cli.db_router items get YOK-N status\n"
                    "See AGENTS.md \"Worktree DB Authority\" rule."
                ),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

def strip_heredoc_bodies(text):
    parts = []
    pos = 0
    while True:
        opener = _heredoc_start_re.search(text, pos)
        if opener is None:
            parts.append(text[pos:])
            return "".join(parts)

        close_pat = re.compile(
            r"(?m)^"
            + (r"\t*" if opener.group("dash") == "-" else "")
            + re.escape(opener.group("delim"))
            + r"\b"
        )
        closer = close_pat.search(text, opener.end())
        if closer is None:
            parts.append(text[pos:])
            return "".join(parts)

        parts.append(text[pos:opener.start()])
        parts.append(opener.group("prefix") + "HEREDOC_STRIPPED" + opener.group("suffix"))
        pos = closer.end()

command = strip_heredoc_bodies(command)

# --- Preprocessing: Strip quoted string interiors ---
# Quoted string content (titles, bodies, descriptions) can contain keywords that
# trigger structural checks (sqlite3, backlog-registry.sh, claude, etc.) even
# though the keyword is just data, not a command invocation. Strip the interior
# of single- and double-quoted strings to prevent false positives.
# Two variables: command_stripped for structural checks (1, 3, 5, 6, 7),
# original command for SQL content checks (2, 4, 8) which intentionally inspect
# quoted string content (SQL queries, awk programs).
_sq = chr(39)
command_stripped = re.sub(_sq + r"[^" + _sq + r"]*" + _sq, _sq + "QUOTED" + _sq, command)
_dq = chr(34)
command_stripped = re.sub(_dq + r"(?:[^" + _dq + r"\\]|\\.)*" + _dq, _dq + "QUOTED" + _dq, command_stripped)

"""

__all__ = ("RULE_TEXT_PREPROCESS",)
