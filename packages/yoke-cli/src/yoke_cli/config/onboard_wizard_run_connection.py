"""Reuse the Yoke connection this setup run already saved.

Machine approval, a self-host first boot and a server backup restore each save
and activate a connection before Review. Choosing the same destination again —
the wizard's Back and Forward, or agent mode replaying the stored destination
answer — continues from that connection instead of asking for a second
approval, starting the server again, or restoring the backup twice. The saved
connection also stays the run's own on the next agent call: the destination
picker that showed before it existed is skipped rather than replaced by a
saved-connection question nobody answered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config.onboard_destinations import DESTINATION_SERVER
from yoke_cli.config.setup_run_facts import CONNECTION

KIND_APPROVED = "approved"
KIND_SELF_HOST = "self-host"
KIND_RESTORED = "restored"


def record_approved(shell: Any) -> None:
    """The browser-approved, invited or token-entered connection is now saved."""
    result = shell.result
    shell._run_facts.record(
        CONNECTION,
        {
            "kind": KIND_APPROVED,
            "choice": getattr(shell, "_destination_row", None) or result.destination,
            "destination": result.destination,
            "api_url": result.api_url,
            "env_name": result.env_name,
            "token_file": result.token_file,
        },
    )


def record_self_host(shell: Any, setup: Any, *, kind: str = KIND_SELF_HOST) -> None:
    """The local server this run started (or restored into) is connected."""
    from yoke_cli.config.onboard_destination_rows import SELF_HOST_SERVER_ROW

    shell._run_facts.record(
        CONNECTION,
        {
            "kind": kind,
            "choice": SELF_HOST_SERVER_ROW,
            "destination": DESTINATION_SERVER,
            "api_url": setup.url,
            "env_name": setup.env_name,
            "directory": str(setup.directory),
            "port": setup.port,
            "connection": setup.connection,
        },
    )


def is_current(shell: Any) -> bool:
    """True when the connection machine config now holds is this run's own."""
    fact = shell._run_facts.get(CONNECTION)
    return bool(fact) and fact.get("api_url") == shell.result.api_url


def resume(shell: Any, choice: str) -> bool:
    """Continue from this run's connection when ``choice`` is the one that made it."""
    fact = shell._run_facts.get(CONNECTION)
    if not fact or fact.get("choice") != choice:
        return False
    if fact["kind"] == KIND_APPROVED:
        _resume_approved(shell, fact)
        return True
    from yoke_cli.config import onboard_wizard_self_host as self_host

    setup = _self_host_setup(shell, fact)
    if fact["kind"] == KIND_RESTORED:
        from yoke_cli.config import onboard_wizard_backup as backup

        self_host.select_connection(shell, setup)
        backup.resume_restored(shell)
        return True
    self_host.goto_complete(shell, setup)
    return True


def _resume_approved(shell: Any, fact: dict[str, Any]) -> None:
    result = shell.result
    result.destination = fact["destination"]
    result.api_url = fact["api_url"]
    result.env_name = fact["env_name"]
    result.token = None
    result.token_file = fact["token_file"]
    result.token_source_kind = "token_file"
    result.yoke_token_verification = None
    shell._stored_yoke_token_available = True
    shell._stored_yoke_attempted = False
    # The saved credential is checked again, then setup continues from the
    # same verified-connection step the approval led to.
    shell._goto_token_source()


def _self_host_setup(shell: Any, fact: dict[str, Any]) -> Any:
    from yoke_cli.config import onboard_self_host_server as server

    return server.SelfHostSetup(
        directory=Path(fact["directory"]),
        config_path=shell.result.config_path,
        env_name=fact["env_name"],
        port=int(fact["port"]),
        bundle_created=True,
        connection=fact.get("connection"),
    )


__all__ = [
    "KIND_APPROVED",
    "KIND_RESTORED",
    "KIND_SELF_HOST",
    "is_current",
    "record_approved",
    "record_self_host",
    "resume",
]
