"""Validator and default for the ``browser_qa_metadata`` structured item field.

Every write path that persists ``browser_qa_metadata`` MUST route through
:func:`validate`. Ad-hoc JSON construction in skill bodies is forbidden.

Schema::

    {
        "browser_testable": bool,
        "visual_outcome": bool,
        "browser_routes": [str, ...],            # normalized leading-slash routes
        "browser_timing_hints_ms": [int, ...],   # milliseconds in (0, 60000]
    }

Normalization rules enforced by :func:`validate`:

- **Booleans** strictly typed. ``visual_outcome=true`` requires
  ``browser_testable=true`` (rejected as contradiction otherwise).
- **Routes** are lowercased, leading-slash-prefixed, trailing-slash-stripped
  except the root ``"/"``, query/fragment stripped, internal whitespace
  rejected, deduplicated, and lexicographically sorted.
- **Timing hints** are integer milliseconds in the inclusive-exclusive range
  ``(0, 60000]``; floats are rounded to nearest integer; deduplicated and
  numerically sorted.
- **Unknown keys** and **missing required keys** are rejected.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict


NEGATIVE_DEFAULT: Dict[str, Any] = {
    "browser_testable": False,
    "visual_outcome": False,
    "browser_routes": [],
    "browser_timing_hints_ms": [],
}

_REQUIRED_KEYS = frozenset(NEGATIVE_DEFAULT.keys())
_MAX_TIMING_MS = 60_000


class BrowserQaMetadataError(ValueError):
    """Raised when a ``browser_qa_metadata`` payload fails schema validation."""


def negative_default() -> Dict[str, Any]:
    """Return a fresh deep copy of :data:`NEGATIVE_DEFAULT`."""
    return copy.deepcopy(NEGATIVE_DEFAULT)


def _normalize_route(raw: Any) -> str:
    if not isinstance(raw, str):
        raise BrowserQaMetadataError(
            f"browser_routes entry must be a string; got {type(raw).__name__}"
        )
    if raw == "":
        raise BrowserQaMetadataError("browser_routes entry is an empty string")
    if any(ch.isspace() for ch in raw):
        raise BrowserQaMetadataError(
            f"browser_routes entry '{raw}' contains internal whitespace"
        )

    route = raw.lower()
    for cut in ("?", "#"):
        idx = route.find(cut)
        if idx >= 0:
            route = route[:idx]
    if route == "":
        raise BrowserQaMetadataError(
            f"browser_routes entry '{raw}' reduced to empty after stripping query/fragment"
        )

    if not route.startswith("/"):
        route = "/" + route
    if len(route) > 1 and route.endswith("/"):
        route = route.rstrip("/") or "/"
    return route


def _normalize_timing(raw: Any) -> int:
    if isinstance(raw, bool):
        raise BrowserQaMetadataError(
            "browser_timing_hints_ms entries must be numeric, not bool"
        )
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        value = int(round(raw))
    else:
        raise BrowserQaMetadataError(
            f"browser_timing_hints_ms entries must be int or float; got {type(raw).__name__}"
        )
    if value <= 0:
        raise BrowserQaMetadataError(
            f"browser_timing_hints_ms entry {value} must be > 0"
        )
    if value > _MAX_TIMING_MS:
        raise BrowserQaMetadataError(
            f"browser_timing_hints_ms entry {value} exceeds {_MAX_TIMING_MS} ms"
        )
    return value


def validate(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a ``browser_qa_metadata`` payload.

    Returns a normalized dict with canonical key ordering, deduplicated and
    sorted list values, and fully normalized route strings. Raises
    :class:`BrowserQaMetadataError` on any schema or value violation.
    """
    if not isinstance(payload, dict):
        raise BrowserQaMetadataError(
            f"browser_qa_metadata must be a JSON object; got {type(payload).__name__}"
        )

    keys = set(payload.keys())
    missing = _REQUIRED_KEYS - keys
    if missing:
        raise BrowserQaMetadataError(
            f"browser_qa_metadata missing required keys: {sorted(missing)}"
        )
    unknown = keys - _REQUIRED_KEYS
    if unknown:
        raise BrowserQaMetadataError(
            f"browser_qa_metadata has unknown keys: {sorted(unknown)}"
        )

    bt = payload["browser_testable"]
    vo = payload["visual_outcome"]
    if not isinstance(bt, bool):
        raise BrowserQaMetadataError("browser_testable must be a strict boolean")
    if not isinstance(vo, bool):
        raise BrowserQaMetadataError("visual_outcome must be a strict boolean")
    if vo and not bt:
        raise BrowserQaMetadataError(
            "visual_outcome=true contradicts browser_testable=false"
        )

    routes_in = payload["browser_routes"]
    if not isinstance(routes_in, list):
        raise BrowserQaMetadataError("browser_routes must be a list")
    normalized_routes = sorted({_normalize_route(r) for r in routes_in})

    timings_in = payload["browser_timing_hints_ms"]
    if not isinstance(timings_in, list):
        raise BrowserQaMetadataError("browser_timing_hints_ms must be a list")
    normalized_timings = sorted({_normalize_timing(t) for t in timings_in})

    return {
        "browser_testable": bt,
        "visual_outcome": vo,
        "browser_routes": normalized_routes,
        "browser_timing_hints_ms": normalized_timings,
    }


def canonical_json(payload: Dict[str, Any]) -> str:
    """Serialize a validated payload to compact, sort-key-stable JSON."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_json_string(raw: str) -> str:
    """Parse *raw* as JSON, validate, and return compact canonical JSON.

    Raises :class:`BrowserQaMetadataError` on empty input, malformed JSON, or
    any schema violation surfaced by :func:`validate`.
    """
    if raw is None or raw == "":
        raise BrowserQaMetadataError("browser_qa_metadata payload is empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserQaMetadataError(f"malformed JSON: {exc}") from exc
    return canonical_json(validate(payload))


NEGATIVE_DEFAULT_JSON = canonical_json(NEGATIVE_DEFAULT)
