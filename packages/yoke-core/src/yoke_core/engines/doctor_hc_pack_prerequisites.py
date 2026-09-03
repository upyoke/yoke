"""Report installed Pack tool prerequisites on the Doctor machine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.packs.prerequisites import (
    collect_installed_pack_prerequisites,
    unsatisfied_prerequisites,
)
from yoke_contracts.packs import PACK_RECEIPT_REL
from yoke_core.engines.doctor_context import resolve_context
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "pack-prerequisites"
TITLE = "Installed Pack tool prerequisites"


def hc_pack_prerequisites(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Fail with per-tool recovery when an installed Pack cannot run."""
    root = resolve_context(conn, args).source_checkout
    if root is None:
        rec.record(
            f"HC-{SLUG}",
            TITLE,
            "FAIL",
            "selected project source checkout is unavailable",
        )
        return
    checkout = Path(root)
    rows = collect_installed_pack_prerequisites(checkout)
    unsatisfied = unsatisfied_prerequisites(rows)
    if unsatisfied:
        rec.record(
            f"HC-{SLUG}",
            TITLE,
            "FAIL",
            "\n".join(_failure_line(row) for row in unsatisfied),
        )
        return
    receipt = checkout / PACK_RECEIPT_REL
    if not receipt.is_file():
        detail = "No Pack receipt is present; no installed prerequisites to probe"
    elif not rows:
        detail = "Installed Packs declare no local tool prerequisites"
    else:
        tools = sorted({str(row["tool"]) for row in rows})
        detail = f"{len(rows)} Pack prerequisite declaration(s) ready: " + ", ".join(
            tools
        )
    rec.record(f"HC-{SLUG}", TITLE, "PASS", detail)


def _failure_line(row: dict[str, Any]) -> str:
    return (
        f"- {row.get('pack')}/{row.get('tool')}: {row.get('code')}: "
        f"{row.get('detail')} Recovery: {row.get('install_recipe')}"
    )


__all__ = ["SLUG", "TITLE", "hc_pack_prerequisites"]
