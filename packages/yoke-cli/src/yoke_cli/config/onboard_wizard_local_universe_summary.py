"""Copy and rows for the local-universe summary the Account step shows."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import local_universe_setup
from yoke_cli.config.setup_prompt import SelectionRow
from yoke_cli.config.setup_run_facts import LOCAL_UNIVERSE_CREATED


def current_state(shell: Any) -> dict[str, Any]:
    """The universe as this run found it: one this run's Apply created reads as new."""
    if shell._run_facts.get(LOCAL_UNIVERSE_CREATED):
        return {"state": local_universe_setup.LOCAL_UNIVERSE_CREATE}
    return local_universe_setup.inspect_local_state(shell.result.config_path)


def local_universe_summary_lines(state: dict[str, Any]) -> list[str]:
    status = str(state.get("state") or local_universe_setup.LOCAL_UNIVERSE_CREATE)
    lines: list[str]
    if status == local_universe_setup.LOCAL_UNIVERSE_VERIFY:
        lines = [
            "Existing private universe: ~/.yoke · embedded Postgres · no account.",
            "Apply verifies it and preserves projects, items, settings, and secrets.",
        ]
        if not state.get("active"):
            lines.append("Apply also makes the local universe your active environment.")
    elif status == local_universe_setup.LOCAL_UNIVERSE_UNAVAILABLE:
        reason = str(state.get("reason") or "the saved local connection is incomplete")
        lines = [
            f"Yoke found a local connection record, but it is not usable: {reason}.",
            "Apply cannot use that record; inspect the named connection first.",
            "Back up first, then run `yoke init --local --force` if this machine "
            "should point at a different local universe.",
        ]
    else:
        lines = [
            "No account is required.",
            "Private data: ~/.yoke · database: embedded Postgres.",
            "Reinstalling Yoke preserves this universe by default.",
            "Start fresh, or bring your account and projects from a backup.",
        ]
    return lines


def local_universe_summary_rows(state: dict[str, Any]) -> list[SelectionRow]:
    if state.get("state") == local_universe_setup.LOCAL_UNIVERSE_UNAVAILABLE:
        return [
            SelectionRow("back", "Back", "previous screen"),
        ]
    if state.get("state") == local_universe_setup.LOCAL_UNIVERSE_VERIFY:
        return [
            SelectionRow("continue", "Use existing", "preserve this database"),
            SelectionRow("back", "Back", "previous screen"),
        ]
    from yoke_cli.config.onboard_wizard_backup import START_ROWS

    return START_ROWS


__all__ = [
    "current_state",
    "local_universe_summary_lines",
    "local_universe_summary_rows",
]
