"""Preprocessing fragment for HOOK_POLICY_SOURCE.

Holds RULE_TEXT_PREPROCESS — the imports, payload parsing, the shared shell
parse (``shell``) whose ``code`` drops heredoc bodies, the inline-Python
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

from yoke_contracts.hook_runner.shell_parse import parse_shell, strip_env_prefix
from yoke_core.domain.lint_command_extract import extract_command

try:
    data = json.load(sys.stdin)
except Exception as exc:
    print("lint-db-cmd: WARN invalid PreToolUse payload: %s" % exc, file=sys.stderr)
    sys.exit(0)

# Claude payload shape is usually:
#   {"tool_name":"Bash","tool_input":{"command":"..."}}
# Subagent payloads vary; the shared extractor tries the known keys.
command = extract_command(data)

if command == "":
    print("lint-db-cmd: WARN PreToolUse payload missing command field (allowing by default)", file=sys.stderr)
    sys.exit(0)

original_command = command

# --- Preprocessing: Strip heredoc bodies ---
# Heredoc body content can contain references to guarded scripts, sqlite3,
# YOKE_SKILL_CONTEXT, etc. as prose, examples, or non-shell code (e.g., Python
# import sqlite3). These are not shell invocations and must not trigger any
# check. The one exception is executed Python payloads that call
# sqlite3.connect with a hardcoded Yoke DB path: those are inspected before
# stripping and denied below. The shared shell parse lifts every body out and
# keeps each opener with its same-line suffix, so later checks still see
# pipeline/redirect commands on the opener line.
# Note: cannot use literal single quotes inside python3 -c string,
# so build regexes with chr(39) for the single-quote character.
_sq = chr(39)
shell = parse_shell(original_command)

def segment_uses_python(text):
    segments = parse_shell(text).segments
    words = segments[-1].argv if segments else ()
    if not words:
        return False
    cmd_word = words[0].rsplit("/", 1)[-1]
    if cmd_word in ("python", "python3"):
        return True
    if cmd_word == "uv" and len(words) > 2 and words[1] == "run":
        nested = words[2].rsplit("/", 1)[-1]
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

def extract_python_payloads(parsed):
    text = parsed.command
    payloads = []
    for heredoc in parsed.heredocs:
        line_start = text.rfind("\n", 0, heredoc.source_operator_start) + 1
        if segment_uses_python(text[line_start:heredoc.source_operator_start]):
            payloads.append(heredoc.body)

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


def extract_yoke_query_sql_payloads(parsed):
    payloads = []
    words = [word for segment in parsed.segments for word in segment.tokens]

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

for py_code in extract_python_payloads(shell):
    if python_uses_literal_yoke_db(py_code):
        result = HookDecision(outcome=Outcome.DENY, message=("BLOCKED: Do not open the Yoke DB from ad-hoc Python using a hardcoded or relative "
                    "path like yoke.db. Use the canonical DB router / Postgres authority instead:\n"
                    "Examples:\n"
                    "  yoke db read \"SELECT ...\"\n"
                    "  yoke items get PREFIX-N status\n"
                    "See `.yoke/docs/agents/rules/databases.md`."), audit_fields={"check_id": 'lint-sqlite-cmd'}, block=True, next=Next.STOP)

        sys.exit(0)

command = shell.code

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
