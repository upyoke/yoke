"""Server-side label-color resolver + per-request override "whiteboard".

The server applies the request-carried label-color overrides — resolved
client-side by the CLI and posted on a per-request ContextVar at the dispatch
boundary — on top of the shared contract defaults. It never reads a file or
resolves a repo root.

The shared defaults, parsing, and delta helpers live in
``yoke_contracts.project_contract.label_policy``; the client-side resolution
(read ``.yoke/labels`` from the checkout) lives in the CLI.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Optional

from yoke_contracts.project_contract.label_policy import (
    read_labels_file,
    resolve_color,
)

__all__ = ["get_color", "request_overrides"]


# Request-scoped label-color overrides ("whiteboard"): the dispatcher posts the
# request's overrides here for the duration of a handler and get_color reads
# them when no explicit overrides are passed. A ContextVar gives each request
# (thread / async task) its own isolated value, so one request's overrides never
# leak into another's colors.
_request_overrides: contextvars.ContextVar[Optional[Mapping[str, str]]] = (
    contextvars.ContextVar("label_color_overrides", default=None)
)


@contextmanager
def request_overrides(overrides: Optional[Mapping[str, str]]) -> Iterator[None]:
    """Post *overrides* on the request-scoped whiteboard for the enclosed block."""
    token = _request_overrides.set(overrides or None)
    try:
        yield
    finally:
        _request_overrides.reset(token)


def get_color(
    key: str,
    default: str,
    *,
    overrides: Optional[Mapping[str, str]] = None,
    policy_path: Path | str | None = None,
) -> str:
    """Resolve a label color: request override, else contract default, else *default*.

    Pure on the server path: no file read, no repo-root resolution. ``overrides``
    is supplied explicitly or read from the per-request whiteboard. ``policy_path``
    reads an explicit labels file (operator/debug and tests) and merges it under
    any caller ``overrides``.
    """
    if policy_path is not None:
        merged = dict(read_labels_file(policy_path))
        merged.update(overrides or {})
        overrides = merged
    elif overrides is None:
        overrides = _request_overrides.get()
    return resolve_color(key, overrides, default) or default
