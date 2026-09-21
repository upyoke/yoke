"""Environment-identity checks for QA execution-target rebind."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_requirement_rebind_endpoint_delta import endpoint_delta
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
    """Same identity, different digest, same resolved host authority."""
    if not isinstance(stored, Mapping) or not isinstance(current, Mapping):
        return False
    if not same_environment_identity(stored, current):
        return False
    if target_digest(stored) == target_digest(current):
        return False
    return not endpoint_delta(stored, current)["authority_changed"]


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
            "identity and differ only in declared facts whose resolved host "
            "authority is unchanged. Rebind the evidence "
            f"with `{REBIND_RECIPE.format(requirement_id=int(requirement_id))}`; "
            "rebinding is not re-verifying. A genuinely different environment, "
            "deployment, subject, or host still needs a fresh deployment/plan "
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


def _environment_row(conn: Any, environment_id: int) -> dict[str, Any] | None:
    if not _table_exists(conn, "environments"):
        return None
    row = query_one(
        conn,
        "SELECT e.id AS environment_id, e.name AS environment_name, e.url, "
        "e.settings, s.name AS site_name FROM environments e "
        "JOIN sites s ON s.id=e.site WHERE e.id=%s",
        (int(environment_id),),
    )
    return dict(row) if row is not None else None


def _row_id(row: Any) -> int:
    if hasattr(row, "keys"):
        return int(row["id"])
    return int(row[0])


def _resolve_live_environment_id(
    conn: Any,
    stored: Mapping[str, Any],
    *,
    plan_id: int | None,
) -> tuple[int, str]:
    """Pick the environment row the snapshot actually ran against.

    ``(plan project, environment name)`` cannot identify that row: names
    repeat across projects, and a plan's project may differ from its
    target environment's owner. Stored id, the plan target, then site
    plus name are the authorities that do.
    """
    stored_id = _int(_mapping(stored.get("environment")).get("id"))
    if stored_id:
        return stored_id, "stored environment.id"
    if plan_id:
        plan = query_one(
            conn,
            "SELECT target_environment_id FROM qa_plans WHERE id=%s",
            (int(plan_id),),
        )
        plan_target = 0 if plan is None else _int(plan["target_environment_id"])
        if plan_target:
            return plan_target, "qa_plans.target_environment_id"
    site_name = str(_mapping(stored.get("site")).get("name") or "")
    env_name = str(_mapping(stored.get("environment")).get("name") or "")
    if site_name and env_name:
        rows = query_rows(
            conn,
            "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
            "WHERE s.name=%s AND e.name=%s",
            (site_name, env_name),
        )
        if len(rows) == 1:
            return _row_id(rows[0]), "stored site.name and environment.name"
        if len(rows) > 1:
            raise QaRebindError(
                f"stored site {site_name!r} and environment {env_name!r} "
                f"resolve to {len(rows)} rows; start a fresh execution or "
                "use sanctioned retirement or supersession"
            )
        raise QaRebindError(
            f"no environment row named {site_name}/{env_name}; start a "
            "fresh execution or use sanctioned retirement or supersession"
        )
    raise QaRebindError(
        "stored target records no environment identity; start a fresh "
        "deployment/plan execution or use sanctioned retirement or "
        "supersession"
    )


def _identity_from_stored(
    stored: Mapping[str, Any], env_row: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble a live identity using the snapshot's project, not the row owner.

    A yoke plan targeting the hosted Yoke API stores the plan's project
    next to the environment's site. Rebuilding from the environment's
    owning project would look like a different identity.
    """
    project = _mapping(stored.get("project"))
    tenant = _mapping(stored.get("tenant"))
    return {
        "project_id": _int(project.get("id")),
        "project_slug": str(project.get("slug") or ""),
        "project_name": str(project.get("name") or ""),
        "tenant_id": _int(tenant.get("id")),
        "tenant_slug": str(tenant.get("slug") or ""),
        "tenant_name": str(tenant.get("name") or ""),
        "site_name": str(env_row["site_name"]),
        "environment_id": int(env_row["environment_id"]),
        "environment_name": str(env_row["environment_name"]),
        "url": env_row["url"],
        "settings": env_row["settings"],
    }


def identity_mismatch_message(
    stored: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    environment_id: int,
    resolved_from: str,
    requirement_id: int | None = None,
) -> str:
    """Name the resolved row and the field it came from next to the snapshot."""
    stored_env = _mapping(stored.get("environment"))
    live_env = _mapping(live.get("environment"))
    stored_site = str(_mapping(stored.get("site")).get("name") or "")
    live_site = str(_mapping(live.get("site")).get("name") or "")
    stored_id = stored_env.get("id")
    stored_id_text = (
        f" id {stored_id}" if stored_id not in (None, "") else " with no environment id"
    )
    head = (
        f"requirement {requirement_id} is bound to a genuinely different "
        "target, not a corrected declaration of the same environment"
        if requirement_id is not None
        else "stored target and live target are not the same environment identity"
    )
    return (
        f"{head}: resolved environment id {environment_id} "
        f"({live_site}/{live_env.get('name')}) from {resolved_from}; "
        f"snapshot named site {stored_site!r} environment "
        f"{stored_env.get('name')!r}{stored_id_text}. Start a fresh "
        "execution or use sanctioned retirement or supersession; "
        "rebinding is not re-verifying"
    )


def _live_target(
    conn: Any,
    stored: Mapping[str, Any],
    *,
    plan_id: int | None = None,
) -> tuple[dict[str, Any], int, str]:
    from yoke_core.domain.deployment_qa_execution_target import (
        is_deployment_execution_target,
    )
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )

    environment_id, resolved_from = _resolve_live_environment_id(
        conn, stored, plan_id=plan_id
    )
    env_row = _environment_row(conn, environment_id)
    if env_row is None:
        raise QaRebindError(
            f"environment id {environment_id} from {resolved_from} could "
            "not be loaded as an execution target; start a fresh execution "
            "or use sanctioned retirement or supersession"
        )
    try:
        live = environment_execution_target(
            conn, _identity_from_stored(stored, env_row), require_runtime_match=False
        )
    except ValueError as exc:
        raise QaRebindError(str(exc)) from exc
    if is_deployment_execution_target(stored):
        kind = str(_mapping(stored.get("environment")).get("kind") or "")
        if kind != "persistent_environment":
            raise QaRebindError(
                "non-persistent deployment targets cannot be rebound from an "
                "environment declaration change; begin a new execution for "
                "the active target"
            )
        stored_id = _int(_mapping(stored.get("environment")).get("id"))
        if stored_id and stored_id != environment_id:
            raise QaRebindError(
                identity_mismatch_message(
                    stored,
                    live,
                    environment_id=environment_id,
                    resolved_from=resolved_from,
                )
            )
        overlaid = json.loads(canonical_target(stored))
        overlaid["endpoints"] = live["endpoints"]
        if "role" in live:
            overlaid["role"] = live["role"]
        return overlaid, environment_id, resolved_from
    if not same_environment_identity(stored, live):
        raise QaRebindError(
            identity_mismatch_message(
                stored,
                live,
                environment_id=environment_id,
                resolved_from=resolved_from,
            )
        )
    return live, environment_id, resolved_from


__all__ = [
    "REBIND_RECIPE",
    "QaRebindError",
    "declaration_correction_applies",
    "different_target_reuse_recovery",
    "identity_mismatch_message",
    "same_environment_identity",
]
