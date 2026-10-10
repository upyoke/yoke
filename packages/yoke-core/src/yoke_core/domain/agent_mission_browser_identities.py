"""The browser identities an exploratory mission needs, as walker instructions.

A mission names the identities it browses as (``browser_identities`` in its
method config). The walker proves each one signed in, site by site, on the
Test Machine after setup and before browsing; an expired site is a human gate
naming the identity, the site and the account, resumed by
``yoke browser authorize --identity NAME`` on that host.
"""

from __future__ import annotations

from typing import Any, Mapping


def walker_identity_dispatch(
    case: Mapping[str, Any], host_command_base: str
) -> tuple[list[str], list[str], str]:
    """Return the identities, their exact verify commands, and the prompt clause."""
    identities = list((case.get("method_config") or {}).get("browser_identities") or [])
    commands = [
        f"{host_command_base} -- yoke browser verify --project PROJECT "
        f"--identity {name} --declarations-json DECLARATIONS_JSON --json"
        for name in identities
    ]
    if not identities:
        return identities, commands, ""
    clause = (
        f"This mission needs browser identities {', '.join(identities)}. "
        "The Test Machine cannot read the project's declarations, so read them "
        "here first with `yoke projects capability-settings get --project "
        "PROJECT --cap-type browser-control --json` and pass its "
        "result.settings_json verbatim as DECLARATIONS_JSON. After setup "
        "succeeds and before browsing, check each identity with "
        + "; ".join(f"`{command}`" for command in commands)
        + ", and pass `--identity NAME` to every step acting as that identity. "
        "A site the check reports expired is WALK_STATUS: HUMAN_GATE naming the "
        "identity, the site and the account from that report; the resume action "
        "is `yoke browser authorize --project PROJECT --identity NAME "
        "--declarations-json DECLARATIONS_JSON` on this host, which opens a "
        "window only for the expired sites. Sign-ins live in the host's "
        "identity store and survive walk-end; there is nothing to save or "
        "restore. "
    )
    return identities, commands, clause


__all__ = ["walker_identity_dispatch"]
