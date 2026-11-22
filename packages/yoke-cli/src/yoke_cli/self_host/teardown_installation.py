"""Remove the machine-side installation associated with a self-host bundle."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from yoke_cli.config import (
    machine_uninstall,
    machine_uninstall_projects,
    machine_uninstall_steps,
)
from yoke_cli.config.machine_uninstall_inventory import UninstallError
from yoke_contracts.machine_config import reader as machine_config, schema


def remove_layers(
    selected: list[str], payload: dict, config: Path
) -> tuple[list[str], list[str]]:
    groups = schema.connection_project_maps(payload)
    checkouts = {
        env: tuple(
            Path(entry["checkout"]).expanduser().resolve()
            for entry in schema.normalize_projects(entries)
        )
        for env, entries in groups.items()
    }
    bound = tuple(
        dict.fromkeys(path for env in selected for path in checkouts.get(env, ()))
    )
    for env, paths in checkouts.items():
        if env not in selected and (shared := set(bound).intersection(paths)):
            names = ", ".join(str(path) for path in sorted(shared))
            raise UninstallError(
                f"teardown_checkout_shared: {names} are also registered under {env}. "
                "Use separate checkouts for the two connections, then retry teardown."
            )

    command = partial(machine_uninstall_steps.command, config=config)
    refusals = machine_uninstall_projects.preflight(bound, config, command)
    if refusals:
        raise UninstallError("\n".join(refusals))
    for env in selected:
        command(["--env", env, "relay", "uninstall"])
    for checkout in bound:
        command(machine_uninstall_projects.project_args(checkout, config))
    return selected, [str(checkout) for checkout in bound]


def finish_machine(config: Path, bundle: Path) -> list[str]:
    """Run full uninstall when every machine connection is gone."""
    default = machine_config.config_path().absolute()
    if any(
        machine_config.load_config(path).get("connections")
        for path in {config, default}
    ):
        return []
    lines: list[str] = []
    code = machine_uninstall.after_self_host_teardown(
        config=config, keep_bundle=bundle, emit=lines.append
    )
    if code:
        raise UninstallError("\n".join(lines))
    return lines
