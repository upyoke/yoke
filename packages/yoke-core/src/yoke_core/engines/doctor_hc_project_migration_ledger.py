"""Validate the selected project's declared rollback-safety ledger."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

SLUG = "project-migration-ledger-contract"
TITLE = "Declared migration ledger answers rollback-safety contract"


def hc_project_migration_ledger_contract(conn, args, rec) -> None:
    """Report membership, serving-floor, and history agreement."""
    from yoke_core.domain import migration_ledger_contract, migration_serving_version
    from yoke_core.domain.migration_history import load_migration_module
    from yoke_core.engines.doctor_project_migration_state import (
        MigrationAuthorityUnavailable,
        MigrationConfigurationError,
        NoMigrationModel,
        ledger_rows,
        resolve_project_migration_state,
    )

    try:
        state = resolve_project_migration_state(conn, args)
    except NoMigrationModel as exc:
        rec.record(SLUG, TITLE, "N/A", str(exc))
        return
    except MigrationConfigurationError as exc:
        rec.record(SLUG, TITLE, "FAIL", str(exc))
        return
    except MigrationAuthorityUnavailable as exc:
        rec.record(SLUG, TITLE, "WARN", str(exc))
        return

    try:
        try:
            rows = ledger_rows(state)
        except Exception as exc:  # noqa: BLE001 - unreadable never passes
            rec.record(
                SLUG, TITLE, "WARN",
                f"cannot read {state.project}.{state.model_name} ledger "
                f"{state.ledger.table}: {exc}",
            )
            return
        history_names = [entry.name for entry in state.history]
        applied = [name for name, _floor in rows]
        newer = migration_ledger_contract.applied_entries_outside_history(
            history_names, applied,
        )
        pending = migration_ledger_contract.pending_entries(
            history_names, applied,
        )
        if pending:
            rec.record(
                SLUG, TITLE, "FAIL",
                f"{len(pending)} entry(ies) not applied here: "
                + ", ".join(pending),
            )
            return

        floors = dict(rows)
        missing_floors: list[str] = []
        invalid_floors: list[str] = []
        for name, recorded in rows:
            if recorded:
                try:
                    Version(str(recorded))
                except InvalidVersion:
                    invalid_floors.append(f"{name}={recorded!r}")
        for entry in state.history:
            module = load_migration_module(entry.path, entry.name)
            declared = migration_serving_version.declared_minimum(module)
            recorded = floors.get(entry.name)
            if declared is not None and not recorded:
                missing_floors.append(entry.name)
        if missing_floors or invalid_floors:
            detail = []
            if missing_floors:
                detail.append(
                    "declared floors absent from applied rows: "
                    + ", ".join(missing_floors)
                )
            if invalid_floors:
                detail.append(
                    "invalid recorded serving floors: "
                    + ", ".join(invalid_floors)
                )
            rec.record(SLUG, TITLE, "FAIL", "; ".join(detail))
            return

        if newer and state.running_version is None:
            source = (
                f"environment variable {state.artifact_version_env_var} is unset"
                if state.artifact_version_env_var
                else "runner.config.artifact_version_env_var is not declared"
            )
            shown = ", ".join(newer[:5])
            more = f" and {len(newer) - 5} more" if len(newer) > 5 else ""
            rec.record(
                SLUG, TITLE, "WARN",
                f"{state.project}.{state.model_name}: membership is current, "
                f"but {len(newer)} applied row(s) are newer than this packaged "
                f"history ({shown}{more}); this is rollback-compatible only "
                "when the running artifact satisfies their recorded serving "
                f"floors, and that comparison is unavailable because {source}",
            )
            return

        if state.running_version is not None:
            stranded: list[str] = []
            for name, recorded in rows:
                if not recorded:
                    continue
                try:
                    safe = migration_serving_version.satisfies_minimum(
                        state.running_version, str(recorded),
                    )
                except migration_serving_version.ServingVersionError as exc:
                    rec.record(SLUG, TITLE, "FAIL", str(exc))
                    return
                if not safe:
                    stranded.append(f"{name} requires {recorded}")
            if stranded:
                rec.record(
                    SLUG, TITLE, "FAIL",
                    f"running artifact {state.running_version} is below "
                    "recorded serving floor(s): " + ", ".join(stranded),
                )
                return
        rec.record(
            SLUG, TITLE, "PASS",
            f"{state.project}.{state.model_name}: {len(applied)} membership "
            f"row(s), serving floors readable via "
            f"{state.ledger.serving_floor_column}"
            + (
                f", rollback floor checked against {state.running_version}"
                if newer and state.running_version else ""
            ),
        )
    finally:
        state.close()


__all__ = ["SLUG", "TITLE", "hc_project_migration_ledger_contract"]
