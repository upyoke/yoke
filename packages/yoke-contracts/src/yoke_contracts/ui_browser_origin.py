"""A process-local mark that a call came from this machine's UI server.

Some decisions may be taken by a person at a browser and by nobody else.
"A person at a browser" cannot be read off a function-call envelope: every
field in one is caller-asserted, and the HTTP layer derives only the actor
from the credential -- the session id travels as the caller wrote it. So a
payload flag, an actor id, or an empty session id can all be typed by an
agent, and none of them establishes origin.

What cannot be typed is the call stack. The UI server sets this mark around
its own in-process dispatch, so it is true exactly when the running process
is that server and the call came through it. It never crosses a wire and no
envelope carries it, which is the whole point: a relayed call arrives
without it, and a session-less call on a machine API token arrives without
it too.

This is a mistake-stopper with an audit trail, not a cryptographic boundary.
On a single workstation every surface shares one operator credential, so a
caller determined to evade this has to import this module and lie on
purpose. That is the line it draws: accidents and convenience are stopped,
deliberate evasion is deliberate.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_UI_BROWSER_ORIGIN: ContextVar[bool] = ContextVar(
    "yoke_ui_browser_origin", default=False
)


@contextmanager
def ui_browser_origin() -> Iterator[None]:
    """Mark the calls made inside this block as UI-server originated."""
    token = _UI_BROWSER_ORIGIN.set(True)
    try:
        yield
    finally:
        _UI_BROWSER_ORIGIN.reset(token)


def ui_browser_origin_active() -> bool:
    """True when the caller is dispatching through this machine's UI server."""
    return bool(_UI_BROWSER_ORIGIN.get())


__all__ = ["ui_browser_origin", "ui_browser_origin_active"]
