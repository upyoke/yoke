"""Executed-versus-carried SQL fragment for HOOK_POLICY_SOURCE.

Holds RULE_TEXT_EXECUTED_SQL — the payload-parsing helpers that tell SQL a
command hands to a database from SQL it merely quotes as data. Concatenated
ahead of the lifecycle fragment, whose Check 15b is the caller; the preprocess
prelude supplies ``ast`` and ``re``.
"""

from __future__ import annotations

RULE_TEXT_EXECUTED_SQL = r"""
# --- SQL an inline program EXECUTES, versus SQL it merely CARRIES ---
# A file-editing program quotes SQL as the data it writes: authoring a pytest
# case whose body reads `cur.execute("UPDATE items SET ...")` puts both the
# execution call and the statement into the command, while the program itself
# only calls read_text/replace/write_text.  Matching either as flat text
# therefore refuses ordinary implementation work.  Parsing answers the real
# question -- does a database call receive this statement -- so the scan reads
# the payload's syntax tree rather than its characters.
_DB_EXECUTION_METHODS = ("execute", "executemany", "executescript")


def _call_attr_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _constant_strings(node):
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _string_bindings(tree):
    # A genuine mutation often names its statement first and executes the
    # variable, so resolve plain ``name = "..."`` assignments.
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        strings = _constant_strings(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name) and strings:
                out[target.id] = strings
    return out


def executed_sql_strings(py_code):
    # SQL strings an inline program hands to a database execution call.
    #
    # An empty list means the program executes no statement at all, so any
    # SQL in it is text it carries.  None means this layer could not settle
    # the question -- the payload does not parse, or a call receives its
    # statement through an expression that cannot be read here -- and the
    # caller must fall back to scanning the whole payload rather than
    # allowing.
    try:
        tree = ast.parse(py_code)
    except SyntaxError:
        return None
    bindings = _string_bindings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_attr_name(node) not in _DB_EXECUTION_METHODS:
            continue
        statement = node.args[0] if node.args else None
        if statement is None:
            continue
        if isinstance(statement, ast.Name):
            resolved = bindings.get(statement.id)
            if resolved is None:
                return None
            found.extend(resolved)
            continue
        strings = _constant_strings(statement)
        if not strings:
            return None
        found.extend(strings)
    return found


def sqlite_memory_only(py_code):
    # True when a sqlite3 connection names an in-memory database. A
    # self-contained rehearsal cannot reach Yoke's control-plane authority.
    return bool(re.search(
        r"sqlite3\s*\.\s*connect\s*\(\s*[rubfRUBF]*[\"'](?::memory:|file::memory:[^\"']*)[\"']",
        py_code,
        re.IGNORECASE,
    ))

"""

__all__ = ("RULE_TEXT_EXECUTED_SQL",)
