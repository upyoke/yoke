"""A connection stand-in that closes when its block ends.

Tests that hand a handler a fixture connection through a context manager
usually yield it and never close it. Production's ``with connect() as
conn:`` does close on exit, so a read placed after that block passes under
the plain stand-in and fails for real — which is how two late identity
reads reached review. Using this instead exercises the exit.

It proxies rather than really closing, because the fixture connection is
shared with the assertions that run after the call; refusing use once the
block is over produces the same failure a closed handle does.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


class ClosedAfterBlock:
    """Delegates to ``conn`` until its block exits, then refuses."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.closed = False

    def __getattr__(self, name: str) -> Any:
        if self.closed:
            raise RuntimeError("connection is closed")
        return getattr(self._conn, name)


@contextmanager
def closing_connection(conn: Any) -> Iterator[ClosedAfterBlock]:
    """Yield ``conn`` proxied, and close the proxy on exit."""
    proxy = ClosedAfterBlock(conn)
    try:
        yield proxy
    finally:
        proxy.closed = True
