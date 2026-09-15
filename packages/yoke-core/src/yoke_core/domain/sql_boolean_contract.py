"""Canonical comparison for PostgreSQL Boolean constraint expressions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


def _map_sql_syntax(value: str, transform: Callable[[str], str]) -> str:
    """Transform syntax outside single-quoted literals, preserving literals."""
    result: list[str] = []
    segment_start = 0
    position = 0
    while position < len(value):
        if value[position] != "'":
            position += 1
            continue
        result.append(transform(value[segment_start:position]))
        literal_start = position
        position += 1
        while position < len(value):
            if value[position] != "'":
                position += 1
                continue
            if position + 1 < len(value) and value[position + 1] == "'":
                position += 2
                continue
            position += 1
            break
        result.append(value[literal_start:position])
        segment_start = position
    result.append(transform(value[segment_start:]))
    return "".join(result)


def _normalize_syntax(value: str) -> str:
    def transform(segment: str) -> str:
        normalized = segment.lower().replace("::text", "").replace('"', "")
        normalized = normalized.replace("btrim(", "trim(")
        return normalized.replace("trim(both from ", "trim(")

    return _map_sql_syntax(value, transform).strip()


def _strip_outer_parentheses(expression: str) -> str:
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quoted = False
        encloses_all = True
        for position, character in enumerate(value):
            if character == "'":
                quoted = not quoted
            elif not quoted:
                depth += character == "("
                depth -= character == ")"
                if depth == 0 and position < len(value) - 1:
                    encloses_all = False
                    break
        if not encloses_all or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _top_level_parts(expression: str, operator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    position = 0
    while position < len(expression):
        character = expression[position]
        if character == "'":
            quoted = not quoted
            position += 1
            continue
        if quoted:
            position += 1
            continue
        depth += character == "("
        depth -= character == ")"
        end = position + len(operator)
        token = expression[position:end]
        before = expression[position - 1] if position else " "
        after = expression[end] if end < len(expression) else " "
        if (
            depth == 0
            and token == operator
            and not (before.isalnum() or before == "_")
            and not (after.isalnum() or after == "_")
        ):
            parts.append(expression[start:position])
            start = end
            position = end
            continue
        position += 1
    if not parts:
        return [expression]
    parts.append(expression[start:])
    return parts


def _boolean_tree(expression: str) -> Any:
    value = _strip_outer_parentheses(expression)
    for operator in ("or", "and"):
        parts = _top_level_parts(value, operator)
        if len(parts) == 1:
            continue
        children: list[Any] = []
        for part in parts:
            child = _boolean_tree(part)
            if isinstance(child, tuple) and child[0] == operator:
                children.extend(child[1])
            else:
                children.append(child)
        return operator, tuple(children)
    return "atom", _map_sql_syntax(value, lambda part: re.sub(r"\s+", "", part))


def canonical_boolean_expression(value: str) -> Any:
    """Normalize spelling and redundant parentheses without losing grouping."""
    normalized = _normalize_syntax(value)
    if normalized.startswith("check"):
        normalized = normalized[len("check") :].strip()
    return _boolean_tree(normalized)


__all__ = ["canonical_boolean_expression"]
