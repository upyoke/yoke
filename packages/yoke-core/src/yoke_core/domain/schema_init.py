"""Schema initialization orchestrator."""

from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_canonical_actors
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.field_note_dash_promotion import (
    ensure_field_note_dash_promotion_schema,
)
from yoke_core.domain.flow_init import (
    converge_flow_catalog,
    create_or_replace_item_progress_view,
)
from yoke_core.domain.github_app_schema import create_github_app_tables
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.ouroboros_entry_corrections import (
    ensure_ouroboros_entry_corrections_schema,
)
from yoke_core.domain.pack_projection import (
    converge_pack_catalog,
    create_pack_projection_tables,
)
from yoke_core.domain.project_onboarding_runs import (
    create_project_onboarding_tables,
)
from yoke_core.domain.project_structure import create_project_structure_tables
from yoke_core.domain.projects_restart_schema import create_project_registry_tables
from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables
from yoke_core.domain.qa_plan_execution_schema import (
    converge_qa_plan_execution_schema,
)
from yoke_core.domain.qa_plan_review_schema import (
    ensure_qa_plan_review_schema,
)
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _connect_raw
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_columns import (
    apply_additive_schema,
    apply_harness_session_columns,
    apply_legacy_data_migrations,
)
from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
)
from yoke_core.domain.schema_init_path_integrity_tables import (
    create_path_integrity_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_work_claim_indexes import (
    create_work_claim_active_uniques,
)
from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL,
    STRATEGY_DOCS_CREATE_TABLE_SQL,
)
from yoke_core.domain.strategy_execution_schema import ensure_strategy_execution_schema
from yoke_core.domain.test_machine_schema import ensure_test_machine_schema
from yoke_core.domain.ui_preferences_schema import create_ui_preference_tables
from yoke_core.domain.workflow_schema import ensure_workflow_schema
from yoke_core.domain.workflow_registry import converge_builtin_workflows


def _converge_registered_command_plans(conn) -> None:
    """Converge command-plan bindings; never fail a boot over them.

    Runs against a universe mid-construction as well as a complete one,
    so it self-skips when the tables it reads are not there yet. A
    binding that cannot be converged leaves verification pointing where
    it already pointed, which is strictly better than refusing to start.
    """
    if not all(
        _table_exists(conn, table)
        for table in ("projects", "qa_plans", "qa_plan_cases", "qa_methods")
    ):
        return
    from yoke_core.domain.qa_command_plan_registration import (
        converge_registered_command_plans,
    )

    try:
        converge_registered_command_plans(conn)
    except Exception:  # noqa: BLE001 - boot availability wins over rebinding
        pass


def converge_core_schema(conn, *, backup_target_dsn: str | None = None) -> None:
    """Bring a database's schema up to the current code.

    Runs every schema-CREATION step — tables, indexes, and strictly additive
    columns — in FK-dependency order, then inserts any missing code-owned
    deployment-flow definitions, and finally applies whatever the ordered
    migration history says this database still owes. Exact recognized built-in
    predecessors may be disabled after their bindings are terminal, while a
    code-owned successor becomes the project default. Modified project
    definitions remain untouched. This runs on every server boot, which is what
    propagates newly deployed tables, columns, built-in flow definitions, and
    pending migrations to existing prod / self-host universes on the boot after
    a deploy (see :func:`yoke_core.api.server_entrypoint.ensure_core_schema`).

    The creation steps themselves stay strictly non-destructive. Destructive
    change is not absent — it is confined to the history, where it is ordered,
    recorded per database, and covered by a restore point, rather than being an
    inline repair nothing can audit.

    When the configured restore-point policy takes a local Postgres dump,
    ``backup_target_dsn`` must explicitly identify ``conn``'s authority. The
    convergence kernel never substitutes an ambient Yoke connection for a
    project database supplied by its caller.

    This is the single source of the schema-creation sequence: :func:`cmd_init`
    runs it, then layers seeds and the birth-only data-shape migrations on top.
    Order matters — ``create_external_identity_tables`` FKs into actors,
    organizations (created by ``create_auth_tables``), and roles, so those
    creation steps precede it.
    """
    # Read born-ness BEFORE creating anything. A database that is already a
    # live universe owes the history; a newborn one gets its schema from this
    # very call and therefore already satisfies every historical entry. After
    # the creation steps run, the two are indistinguishable — which is why
    # ``cmd_init`` calling this first makes an empty ledger useless as a birth
    # signal, and why the question is asked here instead.
    from yoke_core.domain.environment_bootstrap import universe_is_born_on

    was_born = universe_is_born_on(conn)

    create_core_tables(conn)
    create_actor_identity_tables(conn)
    # actor_ui_preferences FKs into actors, so this follows the identity step.
    create_ui_preference_tables(conn)
    ensure_event_schema(conn)
    create_work_claim_active_uniques(conn)
    apply_harness_session_columns(conn)
    create_governed_tables(conn)
    create_path_registry_tables(conn)
    create_path_integrity_tables(conn)
    create_actor_path_claim_tables(conn)
    create_auth_tables(conn)
    create_external_identity_tables(conn)
    create_decision_request_tables(conn)
    create_github_app_tables(conn)
    # QA plans bind to a concrete environment, so site/environment authority
    # must exist before the QA catalog creates that foreign key.
    create_project_registry_tables(conn)
    create_project_onboarding_tables(conn)
    create_pack_projection_tables(conn)
    create_project_structure_tables(conn)
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    # Plans attach to projects, workflows and items; requirements snapshot
    # those plans, so the catalog follows all four authorities.
    create_qa_catalog_tables(conn)
    converge_qa_plan_execution_schema(conn)
    ensure_qa_plan_review_schema(conn)
    ensure_test_machine_schema(conn)
    ensure_field_note_dash_promotion_schema(conn)
    ensure_ouroboros_entry_corrections_schema(conn)
    sync_machine_qa_pack_methods(conn)
    # Where a registered verification command runs is executable
    # configuration too: it follows from code plus the project's declared
    # CI-workflow capability, and registration happens only once, so
    # without this a project keeps whatever binding it was first given.
    _converge_registered_command_plans(conn)
    conn.commit()
    # Strategy authority landed on prod via a since-retired governed
    # migration; fresh envs get the table from the same DDL constant
    # the strategy domain owns.
    conn.execute(STRATEGY_DOCS_CREATE_TABLE_SQL)
    conn.execute(STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL)
    ensure_strategy_execution_schema(conn)
    apply_additive_schema(conn)
    converge_pack_catalog(conn)
    # Built-in deployment flows are executable configuration, not birth-only
    # sample data. Missing definitions and exact code-owned supersessions
    # therefore converge with deployed code on every boot while historical
    # stages and project-authored definitions stay intact.
    converge_flow_catalog(conn)
    # The initial bootstrap creates the view before deployment-run tables land;
    # every subsequent server boot must converge it onto the complete current
    # projection once those tables exist.
    if _table_exists(conn, "deployment_flows"):
        create_or_replace_item_progress_view(conn)
    if _table_exists(conn, "qa_runs"):
        _ensure_qa_runs_verdict_trigger(conn)
    converge_migration_history(
        conn, was_born=was_born, backup_target_dsn=backup_target_dsn,
    )


def converge_migration_history(
    conn, *, was_born: bool, backup_target_dsn: str | None = None,
) -> None:
    """Bring this database up to the ordered migration history.

    Runs last, after every creation step, so an entry can rely on the current
    schema being present. ``was_born`` must be the caller's observation from
    *before* any of those steps ran — see :func:`converge_core_schema`.

    Guarded to real Postgres only, which is what separates an authoritative
    universe from the generic SQLite validation surface
    (``schema_common._using_generic_sqlite_validation`` is exactly this
    predicate, negated). There is no capability check: a project capability
    row cannot gate this, because a freshly born universe has none and would
    silently skip its own history — the failure this whole mechanism exists to
    remove.
    """
    if not db_backend.connection_is_postgres(conn):
        return

    from yoke_contracts.engine_version import installed_engine_version
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_boot_apply import apply_pending, stamp_history
    from yoke_core.domain.migration_restore_point import configured_restore_point
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    history = ordered_entries(history_dir(migration_history_package))
    if not history:
        return

    if not was_born:
        # A newborn database got its schema from the code that owns this
        # history, so every entry is already true of it. Record them and run
        # none: this is Flyway's baseline / Django's fake-initial.
        stamp_history(conn, history, applied_by="birth")
        return

    backup_root, external_restore_point = configured_restore_point()
    apply_pending(
        conn,
        history=history,
        applied_by="boot-converge",
        # The version of the artifact doing the applying. Inside a container
        # this is the wheel version; from a source tree it is empty, which the
        # applier reads as "unresolved" and never refuses on — a checkout is
        # ahead of the entry it carries, not behind it.
        running_version=installed_engine_version(),
        backup_root=backup_root,
        backup_target_dsn=backup_target_dsn,
        external_restore_point=external_restore_point,
    )


def cmd_init() -> None:
    """Create DB and shared tables (idempotent)."""
    conn = _connect_raw("")
    try:
        converge_core_schema(conn, backup_target_dsn=db_backend.resolve_pg_dsn())
        seed_roles_and_permissions(conn)
        seed_default_org(conn)
        apply_legacy_data_migrations(conn)
        # Seed the canonical actors after every other table and column
        # exists. Idempotent on re-run; the human label resolves from the
        # LOCAL_HUMAN_LABEL_ENV injection (pinned by the local-universe
        # birth path to the OS login) and falls back to the label the
        # migrated authoritative DB already maps, so re-init never
        # creates a duplicate human row.
        seed_canonical_actors(conn)
    finally:
        conn.close()
