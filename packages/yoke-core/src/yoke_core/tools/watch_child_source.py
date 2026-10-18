"""Wait for watched-child pipe output on POSIX and Windows."""

from __future__ import annotations

import os
import selectors
import time
from typing import TextIO

from yoke_core.tools.watch_child_lines import ChildLines


class ChildSource:
    """Expose timeout reads over a child pipe on each supported platform."""

    def __init__(self, stream: TextIO) -> None:
        self._reader = ChildLines(stream)
        self._selector: selectors.BaseSelector | None = None
        if os.name == "nt":
            os.set_blocking(self._reader.fd, False)
        else:
            self._selector = selectors.DefaultSelector()
            self._selector.register(stream, selectors.EVENT_READ)

    @property
    def ended(self) -> bool:
        return self._reader.ended

    def read(self, timeout: float) -> list[str] | None:
        """Return available lines, or ``None`` when *timeout* expires."""
        if self._selector is not None:
            if not self._selector.select(timeout=max(0.0, timeout)):
                return None
            return self._reader.read()

        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                return self._reader.read()
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(0.05, remaining))

    def __enter__(self) -> ChildSource:
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._selector is not None:
            self._selector.close()


__all__ = ["ChildSource"]
