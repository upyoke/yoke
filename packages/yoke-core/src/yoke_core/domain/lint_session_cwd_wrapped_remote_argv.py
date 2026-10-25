"""Name the direct ``host-command`` route when a wrapper hides remote argv.

The session-cwd guard exempts the argv a direct ``yoke qa mission
host-command ... --`` call ships to the Test Machine. A walker that wraps
that call in its own script hides the argv from every guard, so a Test
Machine path such as ``/Users/testy/...`` reads as a local target. When the
refused target is in another user's home and no invocation in the call is
``yoke``, the refusal says to call ``host-command`` directly and names the
supported copy command.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell

WRAPPED_REMOTE_ARGV_NOTE = (
    "\nTest Machine path? `{target}` is in another user's home, and no "
    "invocation in this call is `yoke`. A wrapper script hides the argv it "
    "passes to `yoke qa mission host-command`, so no guard can see that the "
    "path is remote. Call host-command directly: its argv after `--` runs on "
    "the Test Machine and is not a local target. To copy a file here, run "
    "`yoke qa mission host-copy ... --from REMOTE_PATH --to LOCAL_FILE`.\n"
)

_HOME_ROOTS = ("/Users/", "/home/")
_SHARED_HOME_DIRS = frozenset({"Shared"})


def _home_owner(path: str) -> str:
    for root in _HOME_ROOTS:
        if path.startswith(root):
            return path[len(root) :].split("/", 1)[0]
    return ""


def wrapped_remote_argv_note(
    command: str | ShellParse, target: str, machine_home: str | None
) -> str:
    """Return the direct-call hint for a refused other-user home target.

    ``machine_home`` is the client's relayed home fact; without it no target
    can be called another user's, so no hint is given.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    owner = _home_owner(target)
    if not machine_home or not parsed.command.strip() or not owner:
        return ""
    if owner in _SHARED_HOME_DIRS:
        return ""
    if _home_owner(machine_home.rstrip("/") + "/") == owner:
        return ""
    if any(segment.program == "yoke" for segment in parsed.segments):
        return ""
    return WRAPPED_REMOTE_ARGV_NOTE.format(target=target)


__all__ = ["WRAPPED_REMOTE_ARGV_NOTE", "wrapped_remote_argv_note"]
