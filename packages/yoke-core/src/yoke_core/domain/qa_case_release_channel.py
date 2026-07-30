"""Fail closed when a QA case names the wrong release channel."""

from __future__ import annotations

import re
from typing import Any, Mapping


_CHANNELS = frozenset({"latest", "stable"})
_ENV_CHANNEL = re.compile(r"\bYOKE_CHANNEL=(latest|stable)\b")


def _walk(value: Any, *, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path=f"{path}[{index}]")
    else:
        yield path, value


def require_case_release_channel(
    case: Mapping[str, Any],
    *,
    expected: str,
) -> None:
    """Reject explicit channel values that differ from the target channel."""
    if not expected:
        return
    for path, value in _walk(case):
        key = path.rsplit(".", 1)[-1]
        declared = value if key == "channel" and value in _CHANNELS else None
        if declared is None and isinstance(value, str):
            match = _ENV_CHANNEL.search(value)
            declared = match.group(1) if match is not None else None
        if declared is not None and declared != expected:
            raise ValueError(
                f"mixed-environment QA release channel at {path}: {declared!r}"
            )


__all__ = ["require_case_release_channel"]
