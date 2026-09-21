"""Bind the Python and JS browser step-key maps so one cannot ship without the other."""

from __future__ import annotations

import re
from collections.abc import Mapping

import pytest

from yoke_contracts.browser_qa_contract import ACTION_STEP_KEYS
from yoke_harness.browser_runtime_home import package_source_root

PYTHON_CONTRACT_PATH = (
    "packages/yoke-contracts/src/yoke_contracts/browser_qa_contract.py"
)
JS_SCHEMA_PATH = (
    "packages/yoke-harness/src/yoke_harness/browser_runtime/src/step-schema.js"
)

_STRING_LITERAL = re.compile(r"""['"]([^'"]+)['"]""")
_ACTION_ENTRY = re.compile(
    r"""(?P<action>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*Object\.freeze\("""
)


def _matching_close(source: str, open_index: int) -> int:
    opener = source[open_index]
    closer = {"{": "}", "[": "]", "(": ")"}[opener]
    depth = 0
    in_string: str | None = None
    i = open_index
    while i < len(source):
        ch = source[i]
        if in_string is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in "'\"":
            in_string = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced {opener!r} starting at index {open_index}")


def extract_action_step_keys(js_source: str) -> dict[str, frozenset[str]]:
    """Parse ``const ACTION_STEP_KEYS = Object.freeze({...})`` from JS source."""

    marker = "const ACTION_STEP_KEYS = Object.freeze("
    start = js_source.find(marker)
    if start < 0:
        raise ValueError(
            f"could not find ACTION_STEP_KEYS in {JS_SCHEMA_PATH}; "
            f"the Python copy lives in {PYTHON_CONTRACT_PATH}"
        )
    open_index = start + len(marker)
    close_index = _matching_close(js_source, open_index)
    body = js_source[open_index + 1 : close_index]
    extracted: dict[str, frozenset[str]] = {}
    for match in _ACTION_ENTRY.finditer(body):
        array_open = match.end()
        if array_open >= len(body) or body[array_open] != "[":
            raise ValueError(
                f"ACTION_STEP_KEYS[{match.group('action')!r}] in {JS_SCHEMA_PATH} "
                "is not an Object.freeze([...]) array"
            )
        array_close = _matching_close(body, array_open)
        keys = frozenset(_STRING_LITERAL.findall(body[array_open : array_close + 1]))
        extracted[match.group("action")] = keys
    if not extracted:
        raise ValueError(
            f"extracted no ACTION_STEP_KEYS entries from {JS_SCHEMA_PATH}; "
            f"the Python copy lives in {PYTHON_CONTRACT_PATH}"
        )
    return extracted


def describe_action_step_key_mismatch(
    python_keys: Mapping[str, frozenset[str]],
    js_keys: Mapping[str, frozenset[str]],
) -> str | None:
    """Return a named asymmetry, or None when the maps match in both directions."""

    python_actions = set(python_keys)
    js_actions = set(js_keys)
    lines: list[str] = []
    only_python = sorted(python_actions - js_actions)
    only_js = sorted(js_actions - python_actions)
    if only_python:
        lines.append(
            f"actions only in Python ({PYTHON_CONTRACT_PATH}): {', '.join(only_python)}"
        )
    if only_js:
        lines.append(f"actions only in JS ({JS_SCHEMA_PATH}): {', '.join(only_js)}")
    for action in sorted(python_actions & js_actions):
        python_extra = sorted(python_keys[action] - js_keys[action])
        js_extra = sorted(js_keys[action] - python_keys[action])
        if not python_extra and not js_extra:
            continue
        parts: list[str] = []
        if python_extra:
            parts.append(
                f"Python ({PYTHON_CONTRACT_PATH}) extra keys: "
                + ", ".join(python_extra)
            )
        if js_extra:
            parts.append(f"JS ({JS_SCHEMA_PATH}) extra keys: " + ", ".join(js_extra))
        lines.append(f"action {action!r}: " + "; ".join(parts))
    if not lines:
        return None
    header = (
        f"ACTION_STEP_KEYS mismatch between {PYTHON_CONTRACT_PATH} and {JS_SCHEMA_PATH}"
    )
    return header + "\n" + "\n".join(lines)


def _load_js_schema_source() -> str:
    schema = package_source_root() / "src" / "step-schema.js"
    return schema.read_text(encoding="utf-8")


def test_action_step_keys_match_python_contract_and_js_schema() -> None:
    js_keys = extract_action_step_keys(_load_js_schema_source())
    assert ACTION_STEP_KEYS, (
        f"{PYTHON_CONTRACT_PATH} has an empty ACTION_STEP_KEYS map; "
        f"the JS copy lives in {JS_SCHEMA_PATH}"
    )
    mismatch = describe_action_step_key_mismatch(ACTION_STEP_KEYS, js_keys)
    if mismatch is not None:
        pytest.fail(mismatch)


def test_extractor_reads_frozen_action_object() -> None:
    source = """
const ACTION_STEP_KEYS = Object.freeze({
  navigate: Object.freeze(['route']),
  type: Object.freeze(['target', 'value']),
});
"""
    assert extract_action_step_keys(source) == {
        "navigate": frozenset({"route"}),
        "type": frozenset({"target", "value"}),
    }


def test_mismatch_message_names_files_action_and_keys() -> None:
    python_keys = {
        "navigate": frozenset({"route"}),
        "screenshot": frozenset({"capture", "label"}),
        "only_python": frozenset({"x"}),
    }
    js_keys = {
        "navigate": frozenset({"route"}),
        "screenshot": frozenset({"capture", "fullPage"}),
        "only_js": frozenset({"y"}),
    }
    message = describe_action_step_key_mismatch(python_keys, js_keys)
    assert message is not None
    assert PYTHON_CONTRACT_PATH in message
    assert JS_SCHEMA_PATH in message
    assert "only_python" in message
    assert "only_js" in message
    assert "action 'screenshot'" in message
    assert "label" in message
    assert "fullPage" in message
    assert describe_action_step_key_mismatch(python_keys, python_keys) is None
