"""Rebind QA evidence when an environment declaration, not the target, moved.

A settings write can change the execution-target digest without changing
which environment row or subject the case ran against. The existing
snapshot reuse, retract, and supersession guards correctly refuse to
launder that evidence onto a different target. This module is the path
those guards do not cover: the same environment identity, same subject,
declared facts only.

Rebinding is not re-verifying. A different environment, deployment, or
subject still needs a fresh execution or sanctioned retirement.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.environment_reference import (
    EnvironmentReferenceError,
    resolve as resolve_environment,
)
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.schema_common import _table_exists


REBIND_RECIPE = (
    "yoke qa requirement rebind-target --requirement-id {requirement_id} "
    "--rationale '...'"
)


class QaRebindError(ValueError):
    """A target rebind was refused; the message names the recovery."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def same_environment_identity(
    stored: Mapping[str, Any], live: Mapping[str, Any]
) -> bool:
    """True when both snapshots name the same environment row and subject kind."""
    if _int(stored.get("schema")) != _int(live.get("schema")):
        return False
    for key in ("tenant", "project"):
        left, right = _mapping(stored.get(key)), _mapping(live.get(key))
        if _int(left.get("id")) != _int(right.get("id")):
            return False
        if str(left.get("slug") or "") != str(right.get("slug") or ""):
            return False
    if str(_mapping(stored.get("site")).get("name") or "") != str(
        _mapping(live.get("site")).get("name") or ""
    ):
        return False
    stored_env, live_env = (
        _mapping(stored.get("environment")),
        _mapping(live.get("environment")),
    )
    if str(stored_env.get("name") or "") != str(live_env.get("name") or ""):
        return False
    stored_id, live_id = _int(stored_env.get("id")), _int(live_env.get("id"))
    if stored_id and live_id and stored_id != live_id:
        return False
    if str(stored_env.get("kind") or "") != str(live_env.get("kind") or ""):
        return False
    stored_deploy, live_deploy = (
        _mapping(stored.get("deployment")),
        _mapping(live.get("deployment")),
    )
    if stored_deploy or live_deploy:
        for field in ("run_id", "stage"):
            if str(stored_deploy.get(field) or "") != str(live_deploy.get(field) or ""):
                return False
        if _int(stored_deploy.get("member_item_id")) != _int(
            live_deploy.get("member_item_id")
        ):
            return False
    stored_obs, live_obs = (
        _mapping(stored.get("observation")),
        _mapping(live.get("observation")),
    )
    if stored_obs or live_obs:
        if _int(stored_obs.get("receipt_id")) != _int(live_obs.get("receipt_id")):
            return False
    return True


def declaration_correction_applies(
    stored: Mapping[str, Any] | None, current: Mapping[str, Any] | None
) -> bool:
    """Same identity, different digest — the declaration moved, not the target."""
    if not isinstance(stored, Mapping) or not isinstance(current, Mapping):
        return False
    if not same_environment_identity(stored, current):
        return False
    return target_digest(stored) != target_digest(current)


def different_target_reuse_recovery(
    *,
    stored_target: Mapping[str, Any] | None,
    current_target: Mapping[str, Any] | None,
    requirement_id: int,
) -> str:
    """Recovery clause for snapshot reuse when the stored digest is stale."""
    if declaration_correction_applies(stored_target or {}, current_target or {}):
        return (
            "the stored target and the current target are the same environment "
            "identity and differ only in declared facts. Rebind the evidence "
            f"with `{REBIND_RECIPE.format(requirement_id=int(requirement_id))}`; "
            "rebinding is not re-verifying. A genuinely different environment, "
            "deployment, or subject still needs a fresh deployment/plan "
            "execution or sanctioned retirement or supersession"
        )
    return (
        "start a fresh deployment/plan execution or use sanctioned "
        "retirement or supersession before rematerializing"
    )


def _identity_row(conn: Any, environment_id: int) -> dict[str, Any] | None:
    if not _table_exists(conn, "organizations") or not _table_exists(
        conn, "environments"
    ):
        return None
    row = query_one(
        conn,
        "SELECT p.id AS project_id, p.slug AS project_slug, p.name AS project_name, "
        "o.id AS tenant_id, o.slug AS tenant_slug, o.name AS tenant_name, "
        "s.name AS site_name, e.id AS environment_id, e.name AS environment_name, "
        "e.url, e.settings FROM environments e JOIN sites s ON s.id=e.site "
        "JOIN projects p ON p.id=s.project_id JOIN organizations o ON o.id=p.org_id "
        "WHERE e.id=%s",
        (int(environment_id),),
    )
    return dict(row) if row is not None else None


def _live_target(conn: Any, stored: Mapping[str, Any]) -> dict[str, Any]:
    from yoke_core.domain.deployment_qa_execution_target import (
        is_deployment_execution_target,
    )
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )

    project_id = _int(_mapping(stored.get("project")).get("id"))
    env_name = str(_mapping(stored.get("environment")).get("name") or "")
    if not project_id or not env_name:
        raise QaRebindError(
            "stored target records no environment identity; start a fresh "
            "deployment/plan execution or use sanctioned retirement or "
            "supersession"
        )
    try:
        ref = resolve_environment(conn, project_id=project_id, name=env_name)
    except EnvironmentReferenceError as exc:
        raise QaRebindError(str(exc)) from exc
    identity = _identity_row(conn, ref.id)
    if identity is None:
        raise QaRebindError(
            f"environment {env_name!r} could not be loaded as an execution target"
        )
    live = environment_execution_target(conn, identity, require_runtime_match=False)
    if is_deployment_execution_target(stored):
        kind = str(_mapping(stored.get("environment")).get("kind") or "")
        if kind != "persistent_environment":
            raise QaRebindError(
                "non-persistent deployment targets cannot be rebound from an "
                "environment declaration change; begin a new execution for "
                "the active target"
            )
        stored_id = _int(_mapping(stored.get("environment")).get("id"))
        if stored_id and stored_id != int(ref.id):
            raise QaRebindError(
                "stored target names a different environment row than the "
                "live declaration; start a fresh execution or use sanctioned "
                "retirement or supersession"
            )
        overlaid = json.loads(canonical_target(stored))
        overlaid["endpoints"] = live["endpoints"]
        if "role" in live:
            overlaid["role"] = live["role"]
        return overlaid
    if not same_environment_identity(stored, live):
        raise QaRebindError(
            "stored target and live target are not the same environment "
            "identity; start a fresh execution or use sanctioned retirement "
            "or supersession"
        )
    return live


def rebind_requirement(
    conn: Any,
    *,
    requirement_id: int,
    rationale: str,
    actor_id: int | None = None,
    db_path: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Point one requirement at the live declaration of its own environment."""
    rationale = str(rationale or "").strip()
    if not rationale:
        raise QaRebindError(
            "rebind requires a rationale explaining why the stored evidence "
            "still answers the live declaration of the same environment"
        )
    row = query_one(
        conn,
        "SELECT id,item_id,epic_id,task_num,deployment_run_id,"
        "qa_kind,qa_phase,execution_target_json,execution_target_digest,"
        "rebound_at,rebound_from_digest,rebind_rationale,rebind_actor_id "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"requirement {requirement_id} not found")
    try:
        stored = json.loads(str(row["execution_target_json"] or ""))
    except (TypeError, ValueError) as exc:
        raise QaRebindError(
            f"requirement {requirement_id} has unreadable target evidence; "
            "preserve it and use sanctioned retirement or supersession"
        ) from exc
    if not isinstance(stored, dict):
        raise QaRebindError(
            f"requirement {requirement_id} has no object execution target; "
            "start a fresh execution or use sanctioned retirement or "
            "supersession"
        )
    live = _live_target(conn, stored)
    old_digest = str(row["execution_target_digest"] or "")
    new_json = canonical_target(live)
    new_digest = target_digest(live)
    if old_digest == new_digest:
        return {
            "requirement_id": int(requirement_id),
            "from_digest": old_digest,
            "to_digest": new_digest,
            "rebound_at": row["rebound_at"],
            "rebind_rationale": row["rebind_rationale"],
            "already_current": True,
        }
    if not declaration_correction_applies(stored, live):
        raise QaRebindError(
            f"requirement {requirement_id} is bound to a genuinely different "
            "target, not a corrected declaration of the same environment. "
            "Start a fresh deployment/plan execution or use sanctioned "
            "retirement or supersession; rebinding is not re-verifying"
        )
    now = iso8601_now()
    conn.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,"
        "execution_target_digest=%s,rebound_at=%s,rebound_from_digest=%s,"
        "rebind_rationale=%s,rebind_actor_id=%s WHERE id=%s",
        (
            new_json,
            new_digest,
            now,
            old_digest,
            rationale,
            actor_id,
            int(requirement_id),
        ),
    )
    if commit:
        conn.commit()
    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementTargetRebound",
        requirement_id=int(requirement_id),
        qa_kind=str(row["qa_kind"] or ""),
        qa_phase=str(row["qa_phase"] or ""),
        rationale=rationale,
        target_row=row,
        extra_detail={"from_digest": old_digest, "to_digest": new_digest},
    )
    return {
        "requirement_id": int(requirement_id),
        "from_digest": old_digest,
        "to_digest": new_digest,
        "rebound_at": now,
        "rebind_rationale": rationale,
        "already_current": False,
    }


__all__ = [
    "REBIND_RECIPE",
    "QaRebindError",
    "declaration_correction_applies",
    "different_target_reuse_recovery",
    "rebind_requirement",
    "same_environment_identity",
]
