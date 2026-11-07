"""Personal folder opt-outs; no server or project mutation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from yoke_contracts.hook_runner.folder_scope import DISABLED_FOLDERS_KEY
from yoke_contracts.machine_config import runtime as machine_config


def _set_folder(args: list[str], *, disabled: bool) -> int:
    action = "disable" if disabled else "enable"
    parser = argparse.ArgumentParser(
        prog=f"yoke folder {action}",
        description="Turn hooks off or on for this folder and its subfolders on this machine.",
        epilog="Enabling removes this folder's entry; a disabled ancestor still applies.",
    )
    parser.add_argument("path", help="Folder path (resolved to its physical absolute path).")
    parsed = parser.parse_args(args)
    folder = Path(parsed.path).expanduser().resolve()
    if not folder.is_dir():
        parser.error("folder_path_invalid: choose an existing directory")
    try:
        config = machine_config.load_config()
        values = config.get(DISABLED_FOLDERS_KEY, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("disabled_folders must be a list of folder paths")
        values = {str(Path(v).expanduser().resolve()) for v in values}
        if disabled:
            values.add(str(folder))
        else:
            values.discard(str(folder))
        config[DISABLED_FOLDERS_KEY] = sorted(values)
        selected = machine_config.config_path()
        selected.parent.mkdir(parents=True, exist_ok=True)
        machine_config.write_config(selected, config)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"folder_config_write_failed: {exc}; repair the machine config and retry.", file=sys.stderr)
        return 1
    from yoke_contracts.hook_runner.folder_scope import disabled_folder

    covering = disabled_folder(folder, config)
    print(f"Hooks disabled by {covering}" if covering else f"Hooks enabled for {folder}")
    return 0


def folder_disable(args: list[str]) -> int:
    return _set_folder(args, disabled=True)


def folder_enable(args: list[str]) -> int:
    return _set_folder(args, disabled=False)


TOOL_SHAPED_SUBCOMMANDS = {
    ("folder", "disable"): folder_disable,
    ("folder", "enable"): folder_enable,
}
TOOL_SHAPED_USAGE = {
    "yoke folder disable": "yoke folder disable PATH",
    "yoke folder enable": "yoke folder enable PATH",
}
