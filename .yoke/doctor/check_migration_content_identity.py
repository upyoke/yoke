"""Compare packaged permanent migration bytes with the connected ledger."""

from __future__ import annotations

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_content_identity import (
    read_content_identity_status,
)
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT


HC_SLUG = "migration-content-identity"
HC_ID = f"HC-{HC_SLUG}"
HC_NAME = "Packaged migration bytes match the connected applied ledger"


def hc_migration_content_identity(conn, args, rec) -> None:
    """Packaged migration bytes match the connected applied ledger."""
    history = ordered_entries(history_dir(migration_history_package))
    try:
        status = read_content_identity_status(
            conn,
            history,
            YOKE_LEDGER_CONTRACT,
        )
    except Exception as exc:  # noqa: BLE001 - absence must never read as green
        rec.record(
            HC_ID,
            HC_NAME,
            "N/A",
            f"applied migration ledger is not reachable: {exc}",
        )
        return
    if status.mismatches:
        detail = "; ".join(
            f"{item.entry_name}: ledger={item.recorded_sha256} "
            f"packaged={item.packaged_sha256}"
            for item in status.mismatches
        )
        rec.record(HC_ID, HC_NAME, "FAIL", detail)
        return
    rec.record(
        HC_ID,
        HC_NAME,
        "PASS",
        f"{len(status.verified)} applied migration digest(s) match",
    )


from yoke_project_checks._declare import self_project_checks  # noqa: E402

PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_NAME, hc_migration_content_identity),
)


__all__ = [
    "HC_NAME",
    "HC_ID",
    "HC_SLUG",
    "PROJECT_HEALTH_CHECKS",
    "hc_migration_content_identity",
]
