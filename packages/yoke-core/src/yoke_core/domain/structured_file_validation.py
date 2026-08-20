"""Whether text is a valid document for the format its filename declares.

A three-way union merge keeps both sides' added lines and never asks what those
lines mean. For an append-oriented list that is exactly right. For a structured
file it is unsound in the most ordinary case there is — two branches adding the
same key — because the union keeps both copies and produces a document no
author wrote.

One instance shipped a GitHub Actions workflow where both sides had added the
same input. The union left duplicate ``description``, ``required``, and
``default`` keys under it; the merge reported every conflict auto-resolved and
committed the tree; GitHub then refused the whole workflow with a 422, ten
minutes later, at a dispatch pointing nowhere near the merge.

The check that catches that is narrower than "does it parse". PyYAML's
``safe_load`` accepts duplicate mapping keys and silently keeps the last one,
so a parse check passes the exact input that caused the incident. Each format
is therefore read by a parser that treats a repeated key as an error, which is
what the real consumers of these files do.

Only the structured formats this repository actually merges are checked. A file
this module does not recognize is not a judgement that its content is fine —
it is the absence of a format to judge it against, which is the correct answer
for the append-oriented text the union merge exists to serve.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

#: Filename suffixes this module knows how to read, lowercased.
YAML_SUFFIXES = (".yml", ".yaml")
JSON_SUFFIXES = (".json",)
TOML_SUFFIXES = (".toml",)


def _reject_duplicate_json_keys(pairs: List[Tuple[str, Any]]) -> dict:
    """Build a JSON object, refusing a repeated key.

    ``json.loads`` keeps the last of a repeated pair without complaint, the
    same way PyYAML does, so the duplicate has to be caught while the pairs are
    still a list.
    """
    seen: dict = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate object key {key!r}")
        seen[key] = value
    return seen


def _yaml_error(text: str) -> Optional[str]:
    from yoke_core.domain.yaml_helper import parse_documents_strictly

    try:
        parse_documents_strictly(text)
    except Exception as exc:  # noqa: BLE001 — any parse failure is a finding
        return str(exc).strip() or type(exc).__name__
    return None


def _json_error(text: str) -> Optional[str]:
    try:
        json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except Exception as exc:  # noqa: BLE001 — any parse failure is a finding
        return str(exc).strip() or type(exc).__name__
    return None


def _toml_error(text: str) -> Optional[str]:
    try:
        import tomllib
    except ImportError:  # Python 3.9-3.10 ship no stdlib tomllib
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        tomllib.loads(text)
    except Exception as exc:  # noqa: BLE001 — any parse failure is a finding
        return str(exc).strip() or type(exc).__name__
    return None


def is_structured_filename(filename: str) -> bool:
    """Whether this module knows a format to judge *filename* against."""
    lowered = filename.lower()
    return lowered.endswith(YAML_SUFFIXES + JSON_SUFFIXES + TOML_SUFFIXES)


def structured_document_error(filename: str, text: str) -> Optional[str]:
    """Return why *text* is not a valid *filename* document, or ``None``.

    ``None`` covers both "this is a valid document" and "this filename names no
    format I read". The caller decides what to do with each; for the union
    merge they are the same answer, because an unrecognized format is the
    append-oriented text union merging is for.
    """
    lowered = filename.lower()
    if lowered.endswith(YAML_SUFFIXES):
        return _yaml_error(text)
    if lowered.endswith(JSON_SUFFIXES):
        return _json_error(text)
    if lowered.endswith(TOML_SUFFIXES):
        return _toml_error(text)
    return None


__all__ = [
    "JSON_SUFFIXES",
    "TOML_SUFFIXES",
    "YAML_SUFFIXES",
    "is_structured_filename",
    "structured_document_error",
]
