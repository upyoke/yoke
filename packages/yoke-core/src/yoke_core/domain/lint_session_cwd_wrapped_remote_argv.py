"""Name the direct ``host-command`` route when a wrapper hides remote argv.

The session-cwd guard exempts the argv a direct ``yoke qa mission
host-command ... --`` call ships to the Test Machine. A walker that wraps
that call in its own script hides the argv from every guard, so a Test
Machine path such as ``/Users/testy/...`` reads as a local target. When the
refused target is in another user's home and no invocation in the call is
``yoke``, the refusal says to call ``host-command`` directly and names the
supported pull step.
"""

from __future__ import annotations

import os

from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    strip_env_prefixes,
    strip_heredoc_syntax,
)
from yoke_core.domain.lint_shell_target_tokens import (
    command_operand_tokens,
    shell_command_segments,
)

WRAPPED_REMOTE_ARGV_NOTE = (
    "\nTest Machine path? `{target}` is in another user's home, and no "
    "invocation in this call is `yoke`. A wrapper script hides the argv it "
    "passes to `yoke qa mission host-command`, so no guard can see that the "
    "path is remote. Call host-command directly: its argv after `--` runs on "
    "the Test Machine and is not a local target. To pull a file, run "
    "`yoke qa mission host-command ... -- base64 -i REMOTE_PATH > "
    "LOCAL.json`, then `jq -r .stdout LOCAL.json | base64 -d > LOCAL_FILE`.\n"
)

_HOME_ROOTS = ("/Users/", "/home/")
_SHARED_HOME_DIRS = frozenset({"Shared"})


def _home_owner(path: str) -> str:
    for root in _HOME_ROOTS:
        if path.startswith(root):
            return path[len(root) :].split("/", 1)[0]
    return ""


def _invokes_yoke(command: str) -> bool:
    for segment in shell_command_segments(strip_heredoc_syntax(command)):
        tokens = strip_env_prefixes(command_operand_tokens(segment))
        if tokens and os.path.basename(tokens[0]) == "yoke":
            return True
    return False


def wrapped_remote_argv_note(
    command: str, target: str, machine_home: str | None
) -> str:
    """Return the direct-call hint for a refused other-user home target."""
    owner = _home_owner(target)
    if not command.strip() or not owner or owner in _SHARED_HOME_DIRS:
        return ""
    home = os.path.expanduser("~") if machine_home is None else machine_home
    if _home_owner(home.rstrip("/") + "/") == owner or _invokes_yoke(command):
        return ""
    return WRAPPED_REMOTE_ARGV_NOTE.format(target=target)


__all__ = ["WRAPPED_REMOTE_ARGV_NOTE", "wrapped_remote_argv_note"]
