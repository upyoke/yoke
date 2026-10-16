"""Schema initialization orchestrator."""

from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_canonical_human
from yoke_core.domain.shipped_execution_instruction import (
    seed_shipped_execution_instruction,
)
from yoke_core.domain.event_registry_converge import converge_event_registry
from yoke_core.domain.flow_init import (
    create_or_replace_item_progress_view,
)
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.model_reference_store import (
    seed_initial_catalog,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.pack_projection import (
    converge_pack_catalog,
)
from yoke_core.domain.postgres_application_role_settings import (
    converge_application_role_settings,
)
from yoke_core.domain.qa_catalog_schema import (
    seed_builtin_qa_methods,
)
from yoke_contracts.schema_authority import (
    refuse_without_serving_build_authority,
)
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _connect_raw, _table_exists
from yoke_core.domain.schema_creation import converge_additive_schema
from yoke_core.domain.schema_init_columns import (
    finalize_initial_schema,
)
from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
from yoke_core.domain.workflow_registry import converge_builtin_workflows


def project_code_owned_rows(conn) -> None:
    """Write the rows this build owns into a schema that is already current.

    Runs after the ordered history, never before it, and the difference is not
    cosmetic. A projection names the columns the current code knows; the
    history is what brings a database's columns to those names. Run a
    projection first and a universe still carrying a retired column meets an
    INSERT naming the current one, which fails — and because boot is
    fail-hard, that universe stops serving instead of converging.

    Ordered among themselves by what they reference: plan bindings name both
    workflows and methods, so they come last.
    """
    converge_builtin_workflows(conn)
    seed_initial_catalog(conn)
    seed_builtin_qa_methods(conn)
    sync_machine_qa_pack_methods(conn)
    converge_pack_catalog(conn)
    converge_event_registry(conn)
    # Where a registered verification command runs is executable configuration
    # too: it follows from code plus the project's declared CI-workflow
    # capability, and registration happens only once, so without this a
    # project keeps whatever binding it was first given.
    _converge_registered_command_plans(conn)
    conn.commit()


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
    from yoke_core.domain.qa_command_plan_convergence import (
        converge_registered_command_plans,
    )

    try:
        converge_registered_command_plans(conn)
    except Exception:  # noqa: BLE001 - boot availability wins over rebinding
        pass


def converge_core_schema(conn, *, backup_target_dsn: str | None = None) -> None:
    """Bring a database up to the current code, in two ordered phases.

    First the schema: every creation step — tables, indexes, and strictly
    additive columns — in FK-dependency order, then whatever the ordered
    migration history says this database still owes. Only once the schema is
    current does :func:`project_code_owned_rows` write the rows the code owns,
    because a projection can only name columns the history has already
    delivered. Exact recognized built-in predecessors may be disabled after
    their bindings are terminal, while a code-owned successor becomes the
    project default. Modified project definitions remain untouched. This runs
    on every server boot, which is what propagates newly deployed tables,
    columns, built-in definitions, and pending migrations to existing prod /
    self-host universes on the boot after a deploy (see
    :func:`yoke_core.api.server_entrypoint.ensure_core_schema`).

    Creation stays additive; destructive changes belong to audited history.

    When the configured restore-point policy takes a local Postgres dump,
    ``backup_target_dsn`` must explicitly identify ``conn``'s authority. The
    convergence kernel never substitutes an ambient Yoke connection for a
    project database supplied by its caller.

    :func:`cmd_init` runs it, then layers seeds and initial schema invariants
    on top. The creation phase itself is
    :func:`yoke_core.domain.schema_creation.converge_additive_schema`, which a
    release driver also runs before its first in-process control-plane call.

    Whether this process may converge at all is a question about the database,
    not about the command that got here: a workstation pointed at a control
    plane it does not serve is refused whatever it is running.
    """
    refuse_without_serving_build_authority("converging a database schema")
    converge_application_role_settings(conn)
    # Read born-ness BEFORE creating anything. A database that is already a
    # live universe owes the history; a newborn one gets its schema from this
    # very call and therefore already satisfies every historical entry. After
    # the creation steps run, the two are indistinguishable — which is why
    # ``cmd_init`` calling this first makes an empty ledger useless as a birth
    # signal, and why the question is asked here instead.
    from yoke_core.domain.environment_bootstrap import universe_is_born_on

    was_born = universe_is_born_on(conn)

    converge_additive_schema(conn)
    # The initial bootstrap creates the view before deployment-run tables land;
    # every subsequent server boot must converge it onto the complete current
    # projection once those tables exist.
    if _table_exists(conn, "deployment_flows"):
        create_or_replace_item_progress_view(conn)
    if _table_exists(conn, "qa_runs"):
        _ensure_qa_runs_verdict_trigger(conn)
    converge_migration_history(
        conn,
        was_born=was_born,
        backup_target_dsn=backup_target_dsn,
    )
    project_code_owned_rows(conn)


def converge_migration_history(
    conn,
    *,
    was_born: bool,
    backup_target_dsn: str | None = None,
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
    from yoke_core.domain.migration_apply_attribution import collect_boot_attribution
    from yoke_core.domain.migration_model_capability_defaults import DEFAULT_MODEL_NAME
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_boot_apply import apply_pending, stamp_history
    from yoke_core.domain.migration_restore_point import configured_restore_point
    from yoke_core.domain.migration_history import history_dir, ordered_entries
    from yoke_core.domain.migration_yoke_ledger import (
        YOKE_LEDGER_CONTRACT,
        converge_yoke_migration_content_schema,
    )

    # Keep this ordering local to the content-aware reader as well as in the
    # broader schema sequence: a legacy ledger cannot be queried for a digest
    # until the additive nullable column exists.
    converge_yoke_migration_content_schema(
        conn,
        repair_existing_guards=False,
    )
    history = ordered_entries(history_dir(migration_history_package))
    if not history:
        return

    if not was_born:
        # A newborn database got its schema from the code that owns this
        # history, so every entry is already true of it. Record them and run
        # none: this is Flyway's baseline / Django's fake-initial.
        stamp_history(
            conn,
            history,
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="birth",
        )
        return

    backup_root, external_restore_point = configured_restore_point()
    apply_pending(
        conn,
        history=history,
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="boot-converge",
        running_version=installed_engine_version(),
        attribution=collect_boot_attribution(
            applied_by="boot-converge",
            running_version=installed_engine_version(),
        ),
        model_name=DEFAULT_MODEL_NAME,
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
        finalize_initial_schema(conn)
        seed_canonical_human(conn)
        seed_shipped_execution_instruction(conn)
    finally:
        conn.close()
