"""Read-only instant inspection inside the existing restored-copy kernel.

Diagnostic copies cannot authorize a release: no boot history or release-driver
mutation runs. Measurements survive the kernel's normal copy/archive cleanup.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import time
from typing import Any, Callable

from yoke_contracts.timestamps import iso8601_now
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan
from yoke_core.tools.stored_instant_census import run_census


GIB = 1024**3


class CopyInspection:
    """One sequential copy's filesystem budget and retained measurements."""

    def __init__(
        self,
        output: Path,
        budget_gib: int,
        min_free_gib: int,
        environment: str,
        emit: Callable[[str], None],
    ) -> None:
        if budget_gib <= 0 or min_free_gib <= 0:
            raise ValueError(
                "copy_budget_invalid: supply positive budget/free-space GiB."
            )
        output.mkdir(parents=True, exist_ok=True)
        self.output, self.environment, self.emit = output, environment, emit
        self.budget, self.min_free = budget_gib * GIB, min_free_gib * GIB
        self.initial_free = shutil.disk_usage(output).free
        if self.initial_free < self.budget + self.min_free:
            raise ValueError(
                "copy_budget_unavailable: reserve budget plus free-space floor "
                "before copying; use a filesystem with sufficient space."
            )
        self.report: dict[str, Any] = {}
        self.started = time.monotonic()
        self.last_progress = self.started
        self.dump: Path | None = None

    def guard(self) -> None:
        free = shutil.disk_usage(self.output).free
        consumed = max(0, self.initial_free - free)
        if self.report:
            self.report["peak_filesystem_consumed_bytes"] = max(
                consumed,
                self.report.get("peak_filesystem_consumed_bytes", 0),
            )
        if free < self.min_free or consumed > self.budget:
            raise RuntimeError(
                "copy_budget_exceeded: copy stopped to preserve its disk budget "
                "and free-space floor; retain measurements and relocate the rehearsal."
            )
        now = time.monotonic()
        if self.dump is not None and now - self.last_progress >= 30:
            self.last_progress = now
            self.save()
            archive = self.dump.stat().st_size if self.dump.exists() else 0
            self.emit(
                f"instant-copy elapsed_seconds={now - self.started:.1f} "
                f"archive_bytes={archive} filesystem_free_bytes={free}"
            )

    def observe(self, stage: str, dump: Path) -> None:
        if stage == "start":
            if dump.parent.stat().st_dev != self.output.stat().st_dev:
                raise ValueError(
                    "copy_budget_filesystem_mismatch: output and copy need the same filesystem."
                )
            self.dump = dump
            self.started = time.monotonic()
            self.report = {
                "database": dump.stem,
                "source_environment": self.environment,
                "started_at": iso8601_now(),
                "diagnostic_only": True,
                "history_applied": False,
                "budget_bytes": self.budget,
                "minimum_free_bytes": self.min_free,
                "initial_free_bytes": self.initial_free,
                "measurements": [],
            }
        free = shutil.disk_usage(dump.parent).free
        measurement = {
            "stage": stage,
            "elapsed_seconds": time.monotonic() - self.started,
            "archive_bytes": dump.stat().st_size if dump.exists() else 0,
            "filesystem_free_bytes": free,
        }
        self.report["measurements"].append(measurement)
        self.save()
        self.emit(f"instant-copy stage={stage} measurements={json.dumps(measurement)}")
        if stage != "cleanup":
            self.guard()

    def save(self) -> None:
        if self.dump is not None:
            (self.output / f"{self.dump.stem}.resources.json").write_text(
                json.dumps(self.report, indent=2) + "\n",
            )

    def inspect(self, conn: Any, _copy_dsn: str) -> str | None:
        """Read the restored source as-is, with neither repair nor convergence."""
        assert self.dump is not None
        try:
            conn.execute("SET LOCAL statement_timeout = '15min'")
            row = conn.execute(
                "SELECT pg_database_size(current_database()), pg_current_wal_lsn()::text"
            ).fetchone()
            self.report["restored_database_bytes"] = row[0]
            self.report["local_wal_lsn_after_restore"] = row[1]
            self.report["wal_scope"] = (
                "local cluster baseline, not a timestamp rewrite measurement"
            )
            self.save()

            def read(query: str) -> dict[str, Any]:
                self.guard()
                cursor = conn.execute(query)
                return {
                    "columns": [column[0] for column in cursor.description],
                    "rows": cursor.fetchall(),
                }

            outcome = run_census(
                read,
                f"{self.environment}/{self.dump.stem}:restored-source",
                self.output / f"{self.dump.stem}.instants.json",
            )
            self.report["census_complete"] = outcome == 0
            self.observe("inspected", self.dump)
            return (
                None
                if outcome == 0
                else "instant_copy_census_incomplete: inspect the retained report before conversion."
            )
        except Exception as exc:
            # No credentials or stored row bodies are included in this receipt.
            detail = str(exc).replace(_copy_dsn, "<dsn>")
            self.report["refusal"] = detail
            self.save()
            return f"instant_copy_census_refused: {detail}"


def inspection_plan(
    plan: RehearsalPlan,
    output: Path,
    budget_gib: int,
    min_free_gib: int,
    environment: str,
    emit: Callable[[str], None] = print,
) -> RehearsalPlan:
    inspection = CopyInspection(output, budget_gib, min_free_gib, environment, emit)
    return replace(
        plan,
        history=(),
        pending_names=lambda _conn, _history: (),
        converge=lambda conn, _dsn: conn.execute("SET TRANSACTION READ ONLY"),
        load_module=None,
        post_converge_validator=inspection.inspect,
        copy_observer=inspection.observe,
        resource_guard=inspection.guard,
    )
