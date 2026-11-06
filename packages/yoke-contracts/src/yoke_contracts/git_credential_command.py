"""Shell-safe commands for Git helpers bound to an explicit machine config."""

from pathlib import Path
import shlex


def helper_command(python: Path, helper: Path, config: Path) -> str:
    return "!" + shlex.join([str(python), str(helper), "--config", str(config)])


def rebind_helper(value: str, selected: Path, snapshot: Path) -> str:
    """Rebind the canonical four-token command; leave other helpers intact."""
    if not value.startswith("!"):
        return value
    try:
        command = shlex.split(value[1:])
    except ValueError:
        return value
    if len(command) != 4 or command[2] != "--config":
        return value
    python, helper, config = map(Path, (command[0], command[1], command[3]))
    if not all(path.is_absolute() for path in (python, helper, config)):
        return value
    if config.resolve() != selected.resolve():
        return value
    return helper_command(python, helper, snapshot)
