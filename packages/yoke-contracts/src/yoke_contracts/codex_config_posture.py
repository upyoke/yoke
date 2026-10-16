"""Merge the unattended posture into Codex's own ``config.toml``.

This is another tool's config file: it holds the operator's model choices,
hook trust, and directory trust beside the two keys Yoke needs. So the pass
edits rather than rewrites — every byte outside the keys it manages survives,
and a key the operator has already set to something else is reported, never
overwritten. What the keys are and why lives in
:mod:`yoke_contracts.harness_unattended_posture`.

Comments written *inside* the value of a managed key are the one thing an
edit cannot preserve, and only when that key's value is actually changing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_unattended_posture import (
    CODEX_POSTURE_KEYS,
    CODEX_PROJECTS_TABLE,
    CODEX_TRUST_LEVEL,
    CODEX_TRUST_LEVEL_KEY,
    codex_project_trust_key,
)

import tomllib


class CodexConfigUnreadable(ValueError):
    """The Codex config exists but does not parse as TOML."""


def parse_config(text: str) -> Dict[str, Any]:
    """Parse Codex config text, or raise :class:`CodexConfigUnreadable`."""
    if not text.strip():
        return {}
    try:
        return dict(tomllib.loads(text))
    except ValueError as exc:
        raise CodexConfigUnreadable(str(exc)) from exc


def _toml_string(value: str) -> str:
    """Quote a value as a TOML basic string, refusing control characters."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"refusing to write control characters: {value!r}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _trust_table_header(checkout: str) -> str:
    key = _toml_string(codex_project_trust_key(checkout))
    return f"[{CODEX_PROJECTS_TABLE}.{key}]"


def _top_level_span(lines: List[str]) -> int:
    """Index of the first table header, i.e. the end of the top-level keys."""
    depth = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if depth == 0 and stripped.startswith("[") and "=" not in stripped:
            return index
        depth += line.count("[") - line.count("]")
        if depth < 0:
            depth = 0
    return len(lines)


def _key_line(lines: List[str], end: int, key: str) -> Optional[int]:
    """Index of a ``key = ...`` line among the top-level keys, or ``None``."""
    for index in range(end):
        stripped = lines[index].strip()
        if not stripped.startswith(key):
            continue
        if stripped[len(key) :].lstrip().startswith("="):
            return index
    return None


def _new_record() -> Dict[str, Any]:
    return {
        "set_keys": [],
        "conflicts": [],
        "trusted_checkout": "",
        "created_file": False,
    }


def changed(record: Dict[str, Any]) -> bool:
    """True when this run's plan writes anything."""
    return bool(record["set_keys"] or record["trusted_checkout"])


def plan(text: str, checkout: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Return the config text the unattended posture requires, plus changes.

    An operator value that differs from what Yoke needs is recorded as a
    conflict and left exactly as it is: widening what a harness runs without
    asking is not a decision to make behind someone's back twice.
    """
    record = _new_record()
    config = parse_config(text)
    wanted: List[Tuple[str, str]] = []
    for key, value in CODEX_POSTURE_KEYS:
        current = config.get(key)
        if current == value:
            continue
        if current is None:
            wanted.append((key, value))
            record["set_keys"].append(key)
        else:
            record["conflicts"].append(f"{key} = {current!r} (Yoke needs {value!r})")

    trust_key = codex_project_trust_key(checkout) if checkout else ""
    if trust_key:
        entry = (config.get(CODEX_PROJECTS_TABLE) or {}).get(trust_key)
        entry = entry if isinstance(entry, dict) else {}
        if entry.get(CODEX_TRUST_LEVEL_KEY) != CODEX_TRUST_LEVEL:
            if CODEX_TRUST_LEVEL_KEY in entry:
                record["conflicts"].append(
                    f"{CODEX_PROJECTS_TABLE}[{trust_key}].{CODEX_TRUST_LEVEL_KEY} = "
                    f"{entry[CODEX_TRUST_LEVEL_KEY]!r} (Yoke needs "
                    f"{CODEX_TRUST_LEVEL!r})"
                )
            else:
                record["trusted_checkout"] = trust_key

    if not changed(record):
        return text, record
    record["created_file"] = not text.strip()
    return _apply(text, wanted, record), record


def _apply(text: str, wanted: List[Tuple[str, str]], record: Dict[str, Any]) -> str:
    lines = text.splitlines()
    if wanted:
        end = _top_level_span(lines)
        inserts = [f"{key} = {_toml_string(value)}" for key, value in wanted]
        # Keep a blank line before whatever table followed, so the inserted
        # keys read as top-level rather than as part of that table.
        if end < len(lines) and lines[end].strip():
            inserts.append("")
        lines[end:end] = inserts
    if record["trusted_checkout"]:
        block = [
            "",
            _trust_table_header(record["trusted_checkout"]),
            f"{CODEX_TRUST_LEVEL_KEY} = {_toml_string(CODEX_TRUST_LEVEL)}",
        ]
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(block)
    return "\n".join(lines) + "\n"


def record_written(target: Path, record: Dict[str, Any]) -> List[str]:
    """Record what a written :func:`plan` changed; return unrecorded reports."""
    values = dict(CODEX_POSTURE_KEYS)
    entries = [ledger.codex_key_entry(target, k, values[k]) for k in record["set_keys"]]
    if record["trusted_checkout"]:
        entries.append(ledger.codex_trust_entry(target, record["trusted_checkout"]))
    reports = (ledger.record(entry) for entry in entries)
    return [f"codex: {report}" for report in reports if report]


def remove_top_level_key(text: str, key: str) -> Optional[str]:
    """Drop one top-level ``key = ...`` line, or ``None`` when it is absent."""
    lines = text.splitlines()
    index = _key_line(lines, _top_level_span(lines), key)
    if index is None:
        return None
    del lines[index]
    # plan() separates inserted keys from a following table with a blank
    # line; once the keys are gone that leaves two in a row.
    if (
        0 < index < len(lines)
        and not lines[index].strip()
        and not lines[index - 1].strip()
    ):
        del lines[index]
    return "\n".join(lines) + "\n" if lines else ""


def remove_trust_table(text: str, checkout_key: str) -> Optional[str]:
    """Drop the trust table :func:`plan` appended, exactly as it wrote it.

    ``None`` when no table with that exact header holds only the trust line —
    an edited or reformatted table is the operator's, not Yoke's.
    """
    lines = text.splitlines()
    header = _trust_table_header(checkout_key)
    trust_line = f"{CODEX_TRUST_LEVEL_KEY} = {_toml_string(CODEX_TRUST_LEVEL)}"
    for index, line in enumerate(lines):
        if line.strip() != header:
            continue
        end = index + 1
        while end < len(lines) and not lines[end].strip().startswith("["):
            end += 1
        body = [entry.strip() for entry in lines[index + 1 : end] if entry.strip()]
        if body != [trust_line]:
            return None
        start = index - 1 if index and not lines[index - 1].strip() else index
        del lines[start:end]
        return "\n".join(lines) + "\n" if lines else ""
    return None


__all__ = [
    "CodexConfigUnreadable",
    "changed",
    "parse_config",
    "plan",
    "record_written",
    "remove_top_level_key",
    "remove_trust_table",
]
