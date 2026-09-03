"""Doctor check for scratch databases left on administered clusters."""

from __future__ import annotations

import shlex

import psycopg

from yoke_core.domain import administered_postgres
from yoke_core.domain.pg_test_db_namespace import SCRATCH_DATABASE_PREFIX
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "administered-scratch-databases"
TITLE = "Administered clusters contain no scratch databases"


def _scratch_database_names(dsn: str) -> tuple[str, ...]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT datname FROM pg_database ORDER BY datname",
        ).fetchall()
    return tuple(
        str(row[0]) for row in rows if str(row[0]).startswith(SCRATCH_DATABASE_PREFIX)
    )


def _drop_recipe(env: str, *, dry_run: bool) -> str:
    suffix = " --dry-run" if dry_run else ""
    return (
        f"YOKE_ENV={shlex.quote(env)} python3 -m "
        f"runtime.api.tools.drop_leftover_test_databases{suffix}"
    )


def hc_administered_scratch_databases(
    _conn,
    _args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Fail when a machine-administered cluster retains test-run databases."""

    targets = administered_postgres.configured_administered_targets()
    if not targets:
        rec.record(
            SLUG,
            TITLE,
            "N/A",
            "this machine has no prod-flagged local-Postgres connection",
        )
        return

    leftovers: list[tuple[str, tuple[str, ...]]] = []
    unreadable: list[str] = []
    for target in targets:
        if not target.dsn:
            unreadable.append(
                f"{target.env}: credential DSN is unavailable; repair the "
                "connection shown by `yoke status`, then rerun Doctor"
            )
            continue
        try:
            names = _scratch_database_names(target.dsn)
        except Exception as exc:  # noqa: BLE001 - one cluster must not hide peers
            unreadable.append(
                f"{target.env}: inspection raised {type(exc).__name__}; restore "
                "its tunnel or credential, then rerun Doctor"
            )
            continue
        if names:
            leftovers.append((target.env, names))

    if leftovers:
        findings: list[str] = []
        for env, names in leftovers:
            findings.append(f"- {env}: {', '.join(names)}")
            findings.append(
                f"  Review: `{_drop_recipe(env, dry_run=True)}`; "
                f"remove manually: `{_drop_recipe(env, dry_run=False)}`"
            )
        if unreadable:
            findings.extend(f"- not inspected: {detail}" for detail in unreadable)
        rec.record(SLUG, TITLE, "FAIL", "\n".join(findings))
        return

    if unreadable:
        rec.record(SLUG, TITLE, "WARN", "\n".join(unreadable))
        return

    labels = ", ".join(target.env for target in targets)
    rec.record(
        SLUG,
        TITLE,
        "PASS",
        f"{labels}: 0 {SCRATCH_DATABASE_PREFIX}* databases",
    )


__all__ = ["SLUG", "TITLE", "hc_administered_scratch_databases"]
