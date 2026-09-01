"""Read runtime knobs back out of a materialized bundle's ``.env``.

The bundle writer owns producing that file; anything that needs to know
how a running bundle is configured — where its API is published, say —
reads it back through here rather than re-parsing it in place.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    DEFAULT_API_PUBLISH_SPEC,
)

ENV_FILE_NAME = ".env"


def read_publish_spec(target: Path | str) -> str:
    """Return the bundle's host publish spec, or the default when unset."""
    try:
        text = (Path(target) / ENV_FILE_NAME).read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_API_PUBLISH_SPEC
    for line in text.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key == API_PUBLISH_ENV:
            return value.strip() or DEFAULT_API_PUBLISH_SPEC
    return DEFAULT_API_PUBLISH_SPEC


__all__ = [
    "ENV_FILE_NAME",
    "read_publish_spec",
]
