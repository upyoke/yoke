"""Read-only Windows gate shared by every setup shell, before durable writes."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from yoke_contracts import onboard_destinations
from yoke_contracts.windows_preflight import verdicts
from yoke_contracts.windows_preflight_facts import collect_facts

NATIVE_GUIDANCE = (
    "Native Windows: keep the checkout, Yoke home and database on a local "
    "NTFS drive and use a normal, per-user shell. If WSL is blocked, continue "
    "with native Windows; do not enable WSL or move the home into a WSL share. "
    "Native runtime acceptance is still pending; this guidance is not a "
    "Windows support claim. For a WSL repository run Yoke inside its distro. "
    "If there is no desktop/browser, use the URL and code printed by yoke connect."
    " For captured output, set cmd to `chcp 65001` or PowerShell's "
    "`[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()`; "
    "in Windows PowerShell 5.1 use `Out-File -Encoding utf8` to save text."
)


def _local_selected(parsed) -> bool:
    """Whether the flags or override already choose the machine-local universe."""
    try:
        destination, _ = onboard_destinations.resolve_choice(
            local_flag=bool(getattr(parsed, "destination_local", False)),
            connect_url=getattr(parsed, "connect_url", None),
            override_value=os.environ.get(onboard_destinations.DESTINATION_OVERRIDE),
        )
    except ValueError:
        return False  # destination resolution names this refusal after the gate
    return destination == onboard_destinations.DESTINATION_LOCAL


def check_setup(parsed) -> bool:
    from yoke_cli.config import machine_config

    facts = collect_facts(
        home=machine_config.config_path(parsed.config_path).parent,
        repo=getattr(parsed, "project_checkout", None) or Path.cwd(),
    )
    rows = verdicts(facts, local=_local_selected(parsed))
    for row in rows:
        print(
            f"{row['severity']} ({row['code']}): {row['message']} {row.get('hint', '')}".rstrip(),
            file=sys.stderr,
        )
    if facts.get("system") == "Windows":
        print(NATIVE_GUIDANCE, file=sys.stderr)
    errors = [row for row in rows if row["severity"] == "error"]
    if errors and getattr(parsed, "agent", False):
        from yoke_cli.config import setup_agent_response

        setup_agent_response.emit(
            setup_agent_response.refused(
                "windows_preflight",
                " ".join(row["message"] + " " + row["hint"] for row in errors),
                None,
            )
        )
    return not errors
