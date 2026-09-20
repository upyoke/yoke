"""Client-readable serving floors for function ids.

The engine registry is the write-time check: ``register()`` refuses an id
absent from the previous serving set that omits ``minimum_serving_version``.
This map is what an HTTPS client may read without importing the engine, so
a typed ``function_version_skew`` can name the floor. Keep it equal to the
floors on registered entries; the registry tests bind the two.
"""

from __future__ import annotations

#: function_id -> minimum serving version. Do not copy already-served ids here.
FUNCTION_MINIMUM_SERVING_VERSIONS: dict[str, str] = {
    "qa.item_plan.retract": "next-release",
}


def declared_minimum_serving_version(function_id: str) -> str:
    """Return the client-readable floor for *function_id*, or empty."""
    return str(FUNCTION_MINIMUM_SERVING_VERSIONS.get(function_id) or "").strip()


__all__ = [
    "FUNCTION_MINIMUM_SERVING_VERSIONS",
    "declared_minimum_serving_version",
]
