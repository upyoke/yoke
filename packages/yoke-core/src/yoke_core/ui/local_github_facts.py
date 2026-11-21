"""This machine's GitHub App user authorization, for the local GitHub page.

The local UI server runs on the operator's machine, so it can name the
GitHub account this machine's authorization belongs to. The packet shape is
the one a hosted shell passes under ``capabilities.data.github``.
"""

from __future__ import annotations

from typing import Any

UNREADABLE_NOTICE = (
    "This machine's GitHub configuration could not be read, so its GitHub "
    "account is unknown. Run `yoke github status` to see why."
)


def machine_github_facts() -> dict[str, Any]:
    from yoke_contracts.machine_config import reader as machine_config

    try:
        github = machine_config.github_config()
    except machine_config.MachineConfigError:
        return {
            "authorization": None,
            "notices": [{"kind": "error", "message": UNREADABLE_NOTICE}],
        }
    authorization = github.get("authorization") if isinstance(github, dict) else None
    if not isinstance(authorization, dict) or not authorization.get("login"):
        return {"authorization": None}
    return {
        "authorization": {
            "login": str(authorization["login"]),
            "status": str(authorization.get("status") or "authorized"),
        }
    }


__all__ = ["UNREADABLE_NOTICE", "machine_github_facts"]
