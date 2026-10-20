"""Current setup observations, separate from saved onboarding decisions."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

from yoke_contracts.onboard_checklist import (
    CHECKLIST_STATUSES,
    FIRST_ITEM_DONE_ROW_ID,
    MACHINE_ROW_IDS,
    REQUIRED_SETUP_ROW_IDS,
    ROW_IDS,
    STATUS_CONFIGURED,
    STATUS_DEFERRED,
    STATUS_NOT_NEEDED,
    STATUS_UNKNOWN,
    STATUS_VERIFIED,
)
from yoke_core.domain.project_onboarding_configuration import profile_changed
from yoke_core.domain.project_onboarding_run_records import ProjectOnboardingRunError


def validate_updates(
    *,
    row_status: Mapping[str, str],
    evidence: Mapping[str, Any],
    blocker: Mapping[str, Any],
    note: Mapping[str, Any],
    metadata: Mapping[str, Any],
    machine_id: str | None,
) -> None:
    for values in (row_status, evidence, blocker, note):
        for row_id in values:
            if row_id not in ROW_IDS:
                raise ProjectOnboardingRunError(
                    f"onboarding_row_invalid: unknown row {row_id}; use checklist row ids."
                )
    if FIRST_ITEM_DONE_ROW_ID in row_status:
        raise ProjectOnboardingRunError(
            f"onboarding_row_observed: {FIRST_ITEM_DONE_ROW_ID} is read from the "
            "project's items; route the first work through /yoke steer and it "
            "verifies when that item reaches done."
        )
    for state in row_status.values():
        if state not in CHECKLIST_STATUSES:
            raise ProjectOnboardingRunError(
                f"onboarding_status_invalid: {state}; use the checklist status vocabulary."
            )
    if (
        any(
            set(values) & MACHINE_ROW_IDS
            for values in (row_status, evidence, blocker, note)
        )
        and not machine_id
    ):
        raise ProjectOnboardingRunError(
            "onboarding_machine_required: machine rows need this machine's stable "
            "identity; run yoke setup, then resume the checklist."
        )
    if machine_id:
        try:
            valid = str(UUID(machine_id)) == machine_id
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ProjectOnboardingRunError(
                "onboarding_machine_invalid: run yoke setup to restore machine identity."
            )
    if set(metadata) & {"machines", "profile_facts"}:
        raise ProjectOnboardingRunError(
            "onboarding_metadata_reserved: machine choices and fact snapshots are managed by the checklist."
        )
    if "execution_profile" in metadata:
        profile = metadata["execution_profile"]
        if not isinstance(profile, dict) or not profile:
            raise ProjectOnboardingRunError(
                "setup_profile_invalid: save a nonempty confirmed profile JSON object."
            )
    try:
        json.dumps([evidence, blocker, note, metadata])
    except (TypeError, ValueError) as exc:
        raise ProjectOnboardingRunError(
            "onboarding_evidence_invalid: provide JSON-serializable setup evidence."
        ) from exc


def read_saved_metadata(raw: str) -> dict[str, Any]:
    try:
        saved = json.loads(raw or "{}")
        if not isinstance(saved, dict) or not isinstance(
            saved.get("machines", {}), dict
        ):
            raise ValueError("invalid saved object")
        if "execution_profile" in saved and (
            not isinstance(saved["execution_profile"], dict)
            or not saved["execution_profile"]
        ):
            raise ValueError("invalid saved profile")
        for machine in saved.get("machines", {}).values():
            if not isinstance(machine, dict) or not isinstance(
                machine.get("rows", {}), dict
            ):
                raise ValueError("invalid machine choices")
            if any(
                not isinstance(row, dict) for row in machine.get("rows", {}).values()
            ):
                raise ValueError("invalid saved row")
        return saved
    except (ValueError, TypeError) as exc:
        raise ProjectOnboardingRunError(
            "setup_saved_evidence_unreadable: ask the control-plane operator to "
            "restore this run from its last valid checkpoint, then reread the checklist."
        ) from exc


def validate_observations(
    observations: Mapping[str, Any],
    machine_id: str | None,
) -> None:
    if set(observations) - MACHINE_ROW_IDS or any(
        not isinstance(value, Mapping)
        or "status" not in value
        or not isinstance(value.get("evidence", {}), Mapping)
        or any(
            not isinstance(value.get(key, ""), str) for key in ("reason", "recovery")
        )
        or set(value) - {"status", "evidence", "reason", "recovery"}
        for value in observations.values()
    ):
        raise ProjectOnboardingRunError(
            "onboarding_observation_invalid: provide machine-local rows with status, evidence, reason and recovery."
        )
    validate_updates(
        row_status={key: value["status"] for key, value in observations.items()},
        evidence=observations,
        blocker={},
        note={},
        metadata={},
        machine_id=machine_id,
    )


def update_machine_choices(
    metadata: Mapping[str, Any],
    *,
    machine_id: str | None,
    checkout_path: str | None,
    machine_config_path: str | None,
    row_status: Mapping[str, str],
    evidence: Mapping[str, Any],
    blocker: Mapping[str, Any],
    note: Mapping[str, Any],
) -> dict[str, Any]:
    saved = json.loads(json.dumps(metadata))
    if not machine_id:
        return saved
    machine = saved.setdefault("machines", {}).setdefault(machine_id, {})
    if checkout_path is not None:
        machine["checkout_path"] = checkout_path
    if machine_config_path is not None:
        machine["machine_config_path"] = machine_config_path
    rows = machine.setdefault("rows", {})
    for field, values in (
        ("status", row_status),
        ("evidence", evidence),
        ("blocker", blocker),
        ("note", note),
    ):
        for row_id, value in values.items():
            if row_id in MACHINE_ROW_IDS:
                rows.setdefault(row_id, {})[field] = value
    return saved


def project_rows(
    rows: list[dict[str, Any]],
    metadata: Mapping[str, Any],
    *,
    machine_id: str | None,
    observations: Mapping[str, Any],
    facts: Mapping[str, Any],
    activation: Mapping[str, Any],
    project_id: int | None,
    project_access: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    machine = (metadata.get("machines") or {}).get(machine_id, {})
    local_choices = machine.get("rows") or {}
    projected = []
    for stored in rows:
        row = dict(stored)
        row_id = row["row_id"]
        local = row_id in MACHINE_ROW_IDS
        choice = local_choices.get(row_id, {}) if local else stored
        row["saved_status"] = choice.get("status", STATUS_UNKNOWN)
        row["saved_evidence"] = choice.get("evidence", {})
        observed = (
            observations.get(row_id) if local else {**facts, **activation}.get(row_id)
        )
        if row_id == "project-permission":
            observed = {
                "status": STATUS_VERIFIED if project_access else STATUS_UNKNOWN,
                "evidence": {"source": "current-project-install-permission"},
                "reason": "" if project_access else "project_access_not_checked",
                "recovery": ""
                if project_access
                else "Read yoke onboard checklist get --project P to check current access.",
            }
        if (
            row_id == "yoke-connection"
            and observed
            and project_access
            and observed["status"] == STATUS_CONFIGURED
        ):
            observed = {
                **observed,
                "status": STATUS_VERIFIED,
                "evidence": {
                    **observed.get("evidence", {}),
                    "checked_by": "authenticated-checklist-call",
                },
            }
        row["scope"] = "machine" if local else "project"
        row["machine_id"] = machine_id if local else None
        if row_id == "human-interview" and metadata.get("execution_profile"):
            if profile_changed(metadata.get("profile_facts"), facts):
                row.update(
                    {
                        "status": STATUS_UNKNOWN,
                        "reason": "setup_profile_changed",
                        "recovery": "Resume /yoke onboard and confirm the changed setup proposal.",
                    }
                )
        if observed is not None:
            row.update(observed)
            if (
                observed["status"] == STATUS_UNKNOWN
                and row_id not in REQUIRED_SETUP_ROW_IDS
                and row_id != FIRST_ITEM_DONE_ROW_ID
                and observed.get("reason") != "setup_owner_unavailable"
                and row["saved_status"]
                in (
                    STATUS_DEFERRED,
                    STATUS_NOT_NEEDED,
                )
            ):
                row["status"] = row["saved_status"]
        elif local:
            row.update(
                {
                    "status": STATUS_UNKNOWN,
                    "evidence": {},
                    "reason": "machine_not_checked",
                    "recovery": "Read yoke onboard checklist on this machine to recheck prerequisites.",
                }
            )
        if local:
            row["note"] = choice.get("note") or ""
            row["blocker"] = row.get("reason") or ""
        projected.append(row)
    required_ids = (
        REQUIRED_SETUP_ROW_IDS
        if project_id is not None
        else REQUIRED_SETUP_ROW_IDS & MACHINE_ROW_IDS
    )
    required = {
        row["row_id"]: row for row in projected if row["row_id"] in required_ids
    }
    unmet = [
        row_id
        for row_id in ROW_IDS
        if row_id in required_ids
        if required.get(row_id, {}).get("status", STATUS_UNKNOWN)
        not in (
            STATUS_CONFIGURED,
            STATUS_VERIFIED,
            STATUS_NOT_NEEDED,
        )
    ]
    return projected, {"ready": not unmet, "unmet_rows": unmet}
