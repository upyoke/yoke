"""Resolve an operator question's subject scope and complete audience."""

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import audiences
from yoke_core.domain.actor_message_recipients import resolve_actor_recipients
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.decision_request_operator_question import invalid
from yoke_core.domain.decision_requests import RoleAuthority, _p
from yoke_core.domain.item_ref_resolution import resolve_item_ref
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.session_message_types import SessionMessageError


def question_target(conn, model, session, actor_id):
    p = _p(conn)
    visible = actor_visible_project_ids(conn, actor_id)
    item_id = resolve_item_ref(conn, model.item) if model.item else None
    item_project = None
    if item_id is not None:
        item_project = conn.execute(
            f"SELECT project_id FROM items WHERE id={p}", (item_id,)
        ).fetchone()[0]
    project_id = (
        resolve_project_id(conn, model.project, visible_project_ids=visible)
        if model.project is not None
        else item_project
    )
    if project_id is None and not model.to and not model.audience:
        project_id = session.get("project_id")
    if project_id is not None and project_id not in visible:
        raise invalid("question project is not visible; select a project you can see")
    if item_project is not None and item_project != project_id:
        raise invalid("item belongs to another project; select its project")
    if model.to and model.audience:
        raise invalid("choose --to or --audience, then retry")
    try:
        recipients = (
            resolve_actor_recipients(
                conn, RecipientSelector(actors=model.to), sender_actor_id=actor_id
            )
            if model.to
            else []
        )
    except SessionMessageError as exc:
        raise invalid(f"{exc.code}: {exc}") from exc
    orgs = {
        int(row[0])
        for row in conn.execute(
            f"SELECT org_id FROM actor_org_roles WHERE actor_id={p}", (actor_id,)
        ).fetchall()
    }
    for recipient in recipients:
        orgs &= recipient.shared_org_ids
    audience_id = org_id = None
    if model.audience:
        # A project audience must belong to the subject project; a project-less
        # audience must be owned by an organization the asker belongs to.
        rows = conn.execute(
            f"SELECT id, org_id FROM audiences WHERE name={p} AND "
            f"(project_id={p} OR (project_id IS NULL AND org_id IN "
            f"(SELECT org_id FROM actor_org_roles WHERE actor_id={p})))",
            (model.audience, project_id, actor_id),
        ).fetchall()
        rows = [row for row in rows if (row[1] is None) == (project_id is not None)]
        if len(rows) != 1:
            raise invalid(
                "audience is missing or ambiguous; select one named audience owned by the question scope"
            )
        audience_id, org_id = rows[0]
        if not audiences.rules_for_audiences(conn, (audience_id,)).get(audience_id):
            raise invalid("empty_audience: select an audience with at least one rule")
    elif project_id is None:
        if not recipients:
            raise invalid(
                "operator_question_audience_required: supply --to or --audience"
            )
        if len(orgs) != 1:
            raise invalid(
                "operator_question_org_ambiguous: choose a named organization audience"
            )
        org_id = next(iter(orgs))
    return {
        "project_id": project_id,
        "org_id": org_id,
        "item_id": item_id,
        "audience_id": audience_id,
        "named_actor_ids": [recipient.actor_id for recipient in recipients],
        "role_authorities": [
            RoleAuthority("project", project_id, role) for role in ("owner", "operator")
        ]
        if not recipients and audience_id is None
        else [],
    }
