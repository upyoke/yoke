"""The project steps of ``yoke uninstall``, preflighted before anything changes.

Every selected checkout's project uninstall runs once in ``--check`` mode
first. A refusal there (a lane with uncommitted work, a dirty tree, a branch
that is not the default) stops the machine uninstall before it removes a
relay, a hook or a server that the project step's retry still needs.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path


def project_args(checkout: Path, config: Path, *, check: bool = False) -> list[str]:
    """The project uninstall command machine uninstall runs for *checkout*."""
    return [
        "project",
        "uninstall",
        str(checkout),
        "--config",
        str(config),
        "--remove-lanes",
        *(["--check"] if check else []),
        "--json",
    ]


def preflight(
    checkouts: tuple[Path, ...],
    config: Path,
    command: Callable[[list[str]], str],
) -> list[str]:
    """Return one ``project PATH: refused (...)`` line per checkout that would refuse."""
    refusals = []
    for checkout in checkouts:
        try:
            command(project_args(checkout, config, check=True))
        except Exception as exc:  # noqa: BLE001 — every refusal is reported by name
            refusals.append(f"project {checkout}: refused ({exc})")
    return refusals


def warnings(args: list[str], stdout: str) -> list[str]:
    """Read the named reasons from a project uninstall JSON report."""
    if args[:2] != ["project", "uninstall"]:
        return []
    try:
        report = json.loads(stdout)
    except ValueError:
        return []
    return list(report.get("warnings") or []) if isinstance(report, dict) else []
