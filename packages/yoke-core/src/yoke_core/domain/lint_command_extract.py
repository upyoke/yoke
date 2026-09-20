"""Engine re-export of the shared PreToolUse command reader.

The implementation lives in ``yoke_contracts.hook_runner.command_extract``
so the product-local hook subset can share it without importing the
engine. Lints keep importing this module.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.command_extract import (
    extract_command,
    is_unresolved_command_token,
    raw_command,
)

__all__ = [
    "extract_command",
    "is_unresolved_command_token",
    "raw_command",
]
