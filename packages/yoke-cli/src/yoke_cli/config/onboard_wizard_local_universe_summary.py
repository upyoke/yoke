"""Copy and rows for the local-universe summary the Account step shows."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import local_universe_setup
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import SelectionRow


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
            "Apply will not replace that record without an explicit force repair.",
            "Back up first, then run `yoke init --local --force` if this machine "
            "should point at a different local universe.",
        ]
    else:
        lines = [
            "No account is required.",
            "Private data: ~/.yoke · database: embedded Postgres.",
            "Reinstalling Yoke preserves this universe by default.",
        ]
    return lines


def local_universe_summary_rows(state: dict[str, Any]) -> list[SelectionRow]:
    if state.get("state") == local_universe_setup.LOCAL_UNIVERSE_UNAVAILABLE:
        return [
            SelectionRow("back", "Back", "choose another Yoke home"),
        ]
    if state.get("state") == local_universe_setup.LOCAL_UNIVERSE_VERIFY:
        return [
            SelectionRow("continue", "Use existing", "preserve this database"),
            SelectionRow("back", "Back", "choose another Yoke home"),
        ]
    return steps.VERIFY_OK_ROWS


__all__ = ["local_universe_summary_lines", "local_universe_summary_rows"]
