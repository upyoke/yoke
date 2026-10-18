"""Seed a bounded Shipping review in the disposable local review universe."""

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.local_demo_seed import _local_human_actor_id
from yoke_core.domain import local_shipping_seed_records as records


def require_render_proof():
    from yoke_core.domain import yoke_connected_env
    from yoke_contracts.machine_config import schema

    env = yoke_connected_env.load_active()
    if (
        env is None
        or env.environment != "render-proof"
        or env.config.get("transport") not in schema.POSTGRES_TRANSPORTS
        or schema.connection_is_prod(env.config)
    ):
        raise RuntimeError(
            "shipping_seed_requires_render_proof: use the non-prod local-postgres "
            "render-proof connection; remote and other universes are unchanged"
        )


def _reader(project_id, actor):
    from yoke_core.domain.actors import seed_human_actor
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.actor_role_grants import grant_actor_project_role

    name = "Shipping restricted review reader"
    with connect() as conn:
        seed_roles_and_permissions(conn)
        found = conn.execute(
            "SELECT id FROM actors WHERE kind='human' AND name=%s", (name,)
        ).fetchall()
        if len(found) > 1:
            raise RuntimeError(
                "shipping_seed_reader_collision: inspect duplicate fixture readers"
            )
        reader = int(found[0][0]) if found else seed_human_actor(conn, name)
        grant_actor_project_role(
            conn,
            actor_id=reader,
            project_id=project_id,
            role_name="viewer",
            granted_by_actor_id=actor,
        )
    return reader


def seed_shipping():
    require_render_proof()
    # Boot owns schema and permanent history before any fixture writer runs.
    from yoke_core.api.server_entrypoint import ensure_core_schema
    from yoke_contracts.control_plane_locality import local_authority_exempt

    with local_authority_exempt():
        ensure_core_schema()
        from yoke_core.domain.deployment_runs_schema import cmd_init

        cmd_init()
    actor = _local_human_actor_id()
    from yoke_core.domain.org_schema import seed_default_org
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.actor_role_grants import grant_actor_org_role

    with connect() as conn:
        seed_roles_and_permissions(conn)
        grant_actor_org_role(
            conn,
            actor_id=actor,
            org_id=seed_default_org(conn),
            role_name="admin",
            granted_by_actor_id=actor,
        )
    projects = records.projects(actor)
    records.flow(projects)
    members = records.items(projects, actor)
    plan_ids = records.plans(projects, members, actor)
    run_ids = records.runs(projects, members)
    reader = _reader(int(projects[0]["id"]), actor)
    with connect() as conn:
        shared = conn.execute(
            "SELECT COUNT(*) FROM (SELECT m.run_id FROM deployment_run_items m "
            "JOIN items i ON i.id=m.item_id WHERE m.run_id=ANY(%s) "
            "GROUP BY m.run_id HAVING COUNT(DISTINCT i.project_id)>1) shared",
            (run_ids,),
        ).fetchone()[0]
        counts = conn.execute(
            "SELECT COUNT(DISTINCT run_id),COUNT(*),COUNT(DISTINCT item_id) "
            "FROM deployment_run_items WHERE run_id=ANY(%s)",
            (run_ids,),
        ).fetchone()
    return {
        "ok": True,
        "scenario": "shipping",
        "universe": "render-proof",
        "fixture_run_ids": run_ids,
        "fixture_plan_ids": plan_ids,
        "project_ids": [int(project["id"]) for project in projects],
        "restricted_reader_actor_id": reader,
        "operator_actor_id": actor,
        "run_count": int(counts[0]),
        "member_attachment_count": int(counts[1]),
        "unique_member_count": int(counts[2]),
        "shared_run_count": int(shared),
        "aux_failure_case": {
            "functions": ["qa.activity.read", "deployment_flows.list"],
            "instructions": "In the review browser only, hold these auxiliary reads pending, then fail them. "
            "Available Shipping cards remain; missing facts show loading/refusal. "
            "Record observed response/card evidence; this seed receipt is not a verdict.",
        },
        "next_step": f"Bind the fixture operator with yoke --env render-proof config bind-actor --actor-id {actor}. "
        "Serve this committed source on render-proof, bind its actual loopback URL, "
        "then run the seeded-population QA case and inspect actual counts/isolation. "
        "Never drive the disabled fixture flow or treat this seed as production proof.",
    }
