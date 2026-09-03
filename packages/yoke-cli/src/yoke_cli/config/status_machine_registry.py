"""This machine's registry standing, reported (and repaired) by ``yoke status``.

``yoke status`` is one of the two connect-time paths, so it is where an
asserted machine id becomes a registered one. A refusal lands in the status
block rather than failing the command — the operator asked what the state of
this machine is, and "registration was refused, here is why" is that answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config.machine_registration import register_this_machine


def attach_machine_registry(
    report: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    """Attach this machine's registry standing, registering it when reachable."""
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    machine = read_machine_id(config_path)
    if not machine:
        report["machine"] = {
            "machine_id": None,
            "registered": False,
            "reason": "machine config has no canonical machine id",
        }
        return report
    if not _control_plane_ready(report):
        report["machine"] = {
            "machine_id": machine,
            "registered": False,
            "reason": "control plane not reachable from this status run",
        }
        return report
    report["machine"] = register_this_machine(config_path)
    return report


def _control_plane_ready(report: Mapping[str, Any]) -> bool:
    # Status already probed the plane; a second unbounded dispatcher call
    # hangs product-wheel `yoke status` when the onboard stub 501s POSTs.
    server = report.get("server") or {}
    if isinstance(server, Mapping) and server.get("reachable") is True:
        return True
    db = report.get("db") or {}
    return (
        isinstance(db, Mapping)
        and db.get("relevant") is True
        and db.get("ok") is True
    )


__all__ = ["attach_machine_registry"]
