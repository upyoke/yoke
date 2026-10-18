"""Resolve linked Git checkouts independently of their directory layout."""

from pathlib import Path
import subprocess

from yoke_contracts.machine_config.schema_connections import MachineConfigContractError
from yoke_contracts import terminal_detached_process


# A checkout's primary never changes while the checkout exists, and the
# machine-local hook resident asks for the same few paths on every hook, so
# each answer is kept for the life of the process. Bounded by clearing: the
# set of directories one process works in is small.
_PRIMARY_BY_ROOT: dict[Path, Path] = {}
_PRIMARY_CACHE_LIMIT = 256


def main_checkout(root: str | Path) -> Path:
    """Return Git's primary checkout, or the supplied root outside Git."""
    root = Path(root).expanduser().resolve()
    if not any((parent / ".git").exists() for parent in (root, *root.parents)):
        return root
    primary = _PRIMARY_BY_ROOT.get(root)
    if primary is None:
        primary = _git_main_checkout(root)
        if len(_PRIMARY_BY_ROOT) >= _PRIMARY_CACHE_LIMIT:
            _PRIMARY_BY_ROOT.clear()
        _PRIMARY_BY_ROOT[root] = primary
        _PRIMARY_BY_ROOT[primary] = primary
    return primary


def registered_worktree_paths(root: str | Path) -> list[Path]:
    """Read Git-registered, existing non-bare checkout paths."""
    root = Path(root).expanduser().resolve()
    if not (root / ".git").exists():
        return [root]
    return _git_worktrees(root)


def _git_main_checkout(root: Path) -> Path:
    return _git_worktrees(root)[0]


def _git_worktrees(root: Path) -> list[Path]:
    try:
        result = terminal_detached_process.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _identity_refusal(root) from exc
    if result.returncode == 0:
        paths = []
        for block in result.stdout.split("\0\0"):
            fields = block.split("\0")
            if fields[0].startswith("worktree ") and "bare" not in fields:
                path = Path(fields[0][9:]).resolve()
                if path.is_dir():
                    paths.append(path)
        if paths:
            return paths
    raise _identity_refusal(root)


def _identity_refusal(root: Path) -> MachineConfigContractError:
    return MachineConfigContractError(
        f"checkout_identity_unavailable: cannot resolve Git's main checkout for {root}; "
        "repair Git access until git worktree list --porcelain succeeds there, then rerun the command"
    )
