"""Byte sequences Cursor's ``hooks.json`` loader mishandles inside commands.

Cursor parses ``.cursor/hooks.json`` as JSONC and strips ``/* ... */``
comments without respecting JSON string boundaries, so a hook command
carrying ``/*`` opens a comment that runs to the next ``*/`` and silently
deletes every hook entry in between. A vertical bar in the ``stop`` and
``sessionEnd`` commands separately stops Cursor spawning any tool hook at
all. Both failures are silent: the file still loads, the missing hooks
simply never fire, so a relay Cursor launch never registers.

Keep every rendered Cursor hook command free of these sequences.
"""

from __future__ import annotations


CURSOR_HOOK_COMMAND_FORBIDDEN_SEQUENCES: tuple[str, ...] = ("/*", "*/", "|")

CURSOR_HOOK_COMMAND_BYTE_REASON = (
    "Cursor parses .cursor/hooks.json as JSONC and strips /* ... */ comments "
    "inside JSON strings, silently deleting every hook entry between a "
    "command containing /* and the next */; a vertical bar in the stop and "
    "sessionEnd commands separately stops every tool hook from spawning. "
    "Keep /*, */ and | out of every rendered Cursor hook command."
)


__all__ = [
    "CURSOR_HOOK_COMMAND_BYTE_REASON",
    "CURSOR_HOOK_COMMAND_FORBIDDEN_SEQUENCES",
]
