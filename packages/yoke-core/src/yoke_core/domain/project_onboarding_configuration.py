"""Authoritative project setup reads and safe change fingerprints."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from yoke_contracts.hosting_posture import POSTURE_NO_YOKE_MANAGED_HOST
from yoke_contracts.onboard_checklist import (
    FIRST_ITEM_DONE_ROW_ID,
    SETUP_HANDOFF_ROW_ID,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
    STATUS_UNKNOWN,
    STATUS_NOT_NEEDED,
    STATUS_VERIFIED,
)
from yoke_core.domain.project_onboarding_schema import _p
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.project_onboarding_run_records import ProjectOnboardingRunError


def _fact(present: bool, source: str, recovery: str) -> dict[str, Any]:
    return {
        "status": STATUS_CONFIGURED if present else STATUS_UNKNOWN,
        "evidence": {"source": source, "present": present},
        "reason": "" if present else "setup_fact_missing",
        "recovery": "" if present else recovery,
    }


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# Rows whose observed facts the confirmed setup profile depends on.
PROFILE_INPUT_ROW_IDS = ("project-identity", "hosting-setup", "migration-model-setup")


def project_facts(conn: Any, project_id: int | None) -> dict[str, dict[str, Any]]:
    """Read existing configuration owners; absent declarations stay unknown."""
    if project_id is None:
        return {}
    p = _p(conn)
    recovery = f"/yoke onboard --project {project_id}"
    owners = {
        "project-identity": "projects",
        "strategy-setup": "strategy_docs",
        "hosting-setup": "project_capabilities",
        "migration-model-setup": "project_capabilities",
        "delivery-setup": "project_structure",
        "verification-command-binding": "qa_plan_project_defaults",
    }
    facts = {
        row_id: {**_fact(False, owner, recovery), "reason": "setup_owner_unavailable"}
        for row_id, owner in owners.items()
    }
    if _table_exists(conn, "projects"):
        present = (
            conn.execute(
                f"SELECT 1 FROM projects WHERE id = {p}", (project_id,)
            ).fetchone()
            is not None
        )
        facts["project-identity"] = _fact(present, "projects", "yoke setup")
    if _table_exists(conn, "strategy_docs"):
        docs = conn.execute(
            "SELECT slug, content FROM strategy_docs "
            f"WHERE project_id = {p} AND archived_at IS NULL",
            (project_id,),
        ).fetchall()
        present = {str(row[0]) for row in docs if str(row[1] or "").strip()}
        complete = {"MISSION", "LANDSCAPE", "VISION", "MASTER-PLAN", "CURRENT-PLAN"}
        facts["strategy-setup"] = _fact(complete <= present, "strategy_docs", recovery)
    if _table_exists(conn, "project_capabilities"):
        settings = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                f"SELECT type, settings FROM project_capabilities WHERE project_id = {p}",
                (project_id,),
            ).fetchall()
        }
        for row_id, cap_type in (
            ("hosting-setup", "aws-admin"),
            ("migration-model-setup", "migration_model"),
        ):
            facts[row_id] = _fact(
                cap_type in settings,
                "project_capabilities",
                recovery,
            )
            facts[row_id]["evidence"]["settings_sha256"] = _digest(
                settings.get(cap_type)
            )
    if _table_exists(conn, "project_structure"):
        facts["delivery-setup"] = _fact(False, "project_structure", recovery)
        rows = conn.execute(
            "SELECT family, payload FROM project_structure "
            f"WHERE project_id = {p} AND family IN ('hosting_posture', 'deploy_defaults')",
            (project_id,),
        ).fetchall()
        for family, raw in ((str(row[0]), str(row[1])) for row in rows):
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("not an object")
            except ValueError as exc:
                raise ProjectOnboardingRunError(
                    "setup_configuration_unreadable: repair the project's "
                    f"{family} declaration through yoke project-structure patch apply."
                ) from exc
            row_id = (
                "hosting-setup" if family == "hosting_posture" else "delivery-setup"
            )
            fact = _fact(True, "project_structure", "")
            if family == "hosting_posture":
                fact["evidence"]["settings_sha256"] = _digest(payload)
                if payload.get("posture") == POSTURE_NO_YOKE_MANAGED_HOST:
                    fact["status"] = STATUS_NOT_NEEDED
            facts[row_id] = fact
    if _table_exists(conn, "qa_plan_project_defaults"):
        bound = conn.execute(
            f"SELECT 1 FROM qa_plan_project_defaults WHERE project_id = {p} LIMIT 1",
            (project_id,),
        ).fetchone()
        facts["verification-command-binding"] = _fact(
            bound is not None, "qa_plan_project_defaults", recovery
        )
    return facts


def profile_snapshot(facts: Any) -> dict[str, Any]:
    """The profile inputs among observed facts, saved with the confirmed profile.

    Strategy docs, delivery defaults and verification command bindings are
    written by later setup steps and ordinary planning, so they stay out:
    those writes never reopen the profile.
    """
    if not isinstance(facts, dict):
        return {}
    return {row_id: facts[row_id] for row_id in PROFILE_INPUT_ROW_IDS if row_id in facts}


def profile_changed(snapshot: Any, facts: dict[str, dict[str, Any]]) -> bool:
    """Whether a profile input changed since the profile was saved, row by row."""
    return profile_snapshot(snapshot) != profile_snapshot(facts)


def first_item_done_fact(
    conn: Any, project_id: int | None
) -> dict[str, dict[str, Any]]:
    """Activation, observed live: the project's first item that reached done.

    Reaching ``done`` already means the item passed its own completion
    obligations (merge, delivery and QA where its workflow requires them).
    The fact stays outside the profile fingerprint: finishing work never
    reopens the confirmed setup profile.
    """
    if project_id is None or not (
        _table_exists(conn, "items") and _table_exists(conn, "projects")
    ):
        return {}
    p = _p(conn)
    row = conn.execute(
        "SELECT pr.public_item_prefix, i.project_sequence, i.title "
        "FROM items i JOIN projects pr ON pr.id = i.project_id "
        f"WHERE i.project_id = {p} AND i.status = 'done' "
        "ORDER BY i.id LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return {
            FIRST_ITEM_DONE_ROW_ID: {
                "status": STATUS_UNKNOWN,
                "evidence": {"source": "items", "present": False},
                "reason": "first_item_not_done",
                "recovery": (
                    "Run /yoke steer CURRENT-PLAN to file and route the first "
                    "work; this row verifies itself when that item reaches done."
                ),
            }
        }
    return {
        FIRST_ITEM_DONE_ROW_ID: {
            "status": STATUS_VERIFIED,
            "evidence": {
                "source": "items",
                "present": True,
                "public_ref": f"{row[0]}-{row[1]}",
                "title": str(row[2]),
            },
            "reason": "",
            "recovery": "",
        }
    }


def repaired_handoff_fact(
    conn: Any, project_id: int | None, stored: Any | None
) -> dict[str, dict[str, Any]]:
    """Clear a handoff row setup blocked on its snapshot once one has landed.

    Setup blocks the row when its snapshot sync failed and names
    ``yoke project snapshot sync`` as the repair. A path snapshot built after
    the row was blocked is that repair's durable proof, so the row reads
    configured from then on, however the snapshot arrived.
    """
    if (
        project_id is None
        or stored is None
        or stored["status"] != STATUS_BLOCKED
        or not _table_exists(conn, "path_snapshots")
    ):
        return {}
    p = _p(conn)
    row = conn.execute(
        "SELECT id, commit_sha FROM path_snapshots "
        f"WHERE project_id = {p} AND built_at > {p} "
        "ORDER BY built_at DESC LIMIT 1",
        (project_id, stored["updated_at"]),
    ).fetchone()
    if row is None:
        return {}
    return {
        SETUP_HANDOFF_ROW_ID: {
            "status": STATUS_CONFIGURED,
            "evidence": {
                "source": "path_snapshots",
                "snapshot_id": int(row[0]),
                "commit_sha": str(row[1]),
            },
            "reason": "",
            "recovery": "",
            "blocker": "",
        }
    }
