"""Two operator choices, then the ordered full-machine removal."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from yoke_cli.config.machine_uninstall_inventory import (
    Inventory,
    UninstallError,
    inspect,
)
from yoke_cli.config import machine_uninstall_steps as steps


def run(
    *,
    backup: bool | None,
    projects: str | None,
    non_interactive: bool,
    emit: Callable[[str], None] = print,
    ask: Callable[[str], str] = input,
) -> int:
    inventory = inspect()

    def choose(prompt: str) -> str:
        try:
            return ask(prompt)
        except EOFError as exc:
            raise UninstallError(
                "uninstall_cancelled: no choice was received. Run uninstall again "
                "interactively or supply the project and applicable backup flags."
            ) from exc

    if inventory.owns_data:
        emit(
            "WARNING: This machine holds the only copy of its local universe data. "
            "Uninstall deletes that data permanently."
        )
        if backup is None:
            if non_interactive:
                raise UninstallError(
                    "uninstall_backup_choice_required: choose --backup or --no-backup "
                    "and run uninstall again. --yes never chooses data loss."
                )
            choice = choose(
                "Data: back up first / uninstall without backing up [backup/no-backup]: "
            )
            if choice.strip().lower() not in {"backup", "no-backup"}:
                raise UninstallError(
                    "uninstall_backup_choice_invalid: rerun and choose backup or no-backup."
                )
            backup = choice.strip().lower() == "backup"
    elif backup is not None:
        raise UninstallError(
            "uninstall_backup_not_applicable: this machine holds no universe; omit the backup flag."
        )

    # Validate unattended choices before exporting or touching a checkout.
    if projects is None and non_interactive:
        raise UninstallError(
            "uninstall_projects_choice_required: pass --projects all, none, or PATH,... and retry."
        )
    if projects is not None:
        selected = select_projects(projects, inventory)
    if backup:
        steps.back_up(inventory, emit)
    else:
        emit(
            "backup: skipped (operator chose no backup)"
            if inventory.owns_data
            else "backup: skipped (no local universe or self-host server)"
        )
    emit("Yoke-installed registered checkouts:")
    for index, checkout in enumerate(inventory.projects, 1):
        emit(f"  {index}. {checkout}")
    if not inventory.projects:
        emit("  none")
    if projects is None:
        projects = choose(
            "Remove Yoke from projects [all/none/comma-separated numbers or paths]: "
        )
        selected = select_projects(projects, inventory)
    return steps.remove(inventory, selected, emit)


def select_projects(value: str, inventory: Inventory) -> tuple[Path, ...]:
    token = value.strip()
    if token == "all":
        return inventory.projects
    if token == "none":
        return ()
    selected: list[Path] = []
    for raw in token.split(","):
        raw = raw.strip()
        if raw.isdigit() and 1 <= int(raw) <= len(inventory.projects):
            checkout = inventory.projects[int(raw) - 1]
        else:
            checkout = Path(raw).expanduser().resolve()
        if not raw or checkout not in inventory.projects:
            raise UninstallError(
                f"uninstall_project_not_registered: {raw!r}; choose all, none, "
                "or a checkout shown in the list and retry."
            )
        if checkout not in selected:
            selected.append(checkout)
    return tuple(selected)
