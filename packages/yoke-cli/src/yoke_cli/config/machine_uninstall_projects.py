"""The project steps of ``yoke uninstall``, preflighted before anything changes.

Every selected checkout's project uninstall runs once in ``--check`` mode
first. A refusal there (a lane with uncommitted work, a dirty tree, a branch
that is not the default) stops the machine uninstall before it removes a
relay, a hook or a server that the project step's retry still needs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yoke_cli.config.machine_uninstall_inventory import Inventory


def project_args(checkout: Path, inventory: Inventory, *, check: bool = False) -> list[str]:
    """The project uninstall command machine uninstall runs for *checkout*."""
    return [
        "project",
        "uninstall",
        str(checkout),
        "--config",
        str(inventory.config),
        "--remove-lanes",
        *(["--check"] if check else []),
        "--json",
    ]


def preflight(
    inventory: Inventory,
    selected: tuple[Path, ...],
    command: Callable[[list[str]], str],
) -> list[str]:
    """Return one ``project PATH: refused (...)`` line per checkout that would refuse."""
    refusals = []
    for checkout in inventory.projects:
        if checkout not in selected:
            continue
        try:
            command(project_args(checkout, inventory, check=True))
        except Exception as exc:  # noqa: BLE001 — every refusal is reported by name
            refusals.append(f"project {checkout}: refused ({exc})")
    return refusals
