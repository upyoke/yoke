"""The creation phase of schema convergence: tables, indexes, additive columns.

Every step is idempotent and creates what the current code declares without
rewriting data, so a database already serving an older build keeps serving
it: older code ignores tables and columns it never names. That property is
what lets two callers run the same phase:

- :func:`yoke_core.domain.schema_init.converge_core_schema` runs it first on
  every boot, before the ordered migration history and code-owned rows.
- :mod:`yoke_core.domain.release_start_schema` runs it before a release's
  driver first reads or writes its control-plane database in-process, so the
  new code never meets a column only its own boot would have added.

Ordered history (destructive changes, backfills, restore points) and the
code-owned row projections stay with boot alone.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.events_function_index import ensure_function_index
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.field_note_dash_promotion import (
    ensure_field_note_dash_promotion_schema,
)
from yoke_core.domain.flow_init import converge_flow_catalog
from yoke_core.domain.gate_satisfaction_schema import (
    create_gate_satisfaction_tables,
)
from yoke_core.domain.github_app_schema import create_github_app_tables
from yoke_core.domain.harness_machine_schema import ensure_harness_machine_schema
from yoke_core.domain.health_runs_schema import ensure_doctor_runs_schema
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_core.domain.model_reference_store import create_model_reference_table
from yoke_core.domain.ouroboros_entry_corrections import (
    ensure_ouroboros_entry_corrections_schema,
)
from yoke_core.domain.pack_projection import create_pack_projection_tables
from yoke_core.domain.project_onboarding_runs import (
    create_project_onboarding_tables,
)
from yoke_core.domain.project_structure import create_project_structure_tables
from yoke_core.domain.projects_restart_schema import create_project_registry_tables
from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables
from yoke_core.domain.qa_host_wait_schema import ensure_qa_host_wait_schema
from yoke_core.domain.qa_plan_execution_schema import converge_qa_plan_execution_schema
from yoke_core.domain.qa_plan_review_schema import ensure_qa_plan_review_schema
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_columns import (
    apply_additive_schema,
    apply_harness_session_columns,
    apply_work_claim_scope_column,
)
from yoke_core.domain.schema_init_path_integrity_tables import (
    create_path_integrity_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
)
from yoke_core.domain.schema_init_work_claim_indexes import (
    create_work_claim_active_uniques,
)
from yoke_core.domain.schema_ouroboros_columns import apply_ouroboros_columns
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL,
    STRATEGY_DOCS_CREATE_TABLE_SQL,
)
from yoke_core.domain.strategy_execution_schema import ensure_strategy_execution_schema
from yoke_core.domain.ui_preferences_schema import create_ui_preference_tables
from yoke_core.domain.universe_levels import create_universe_settings_table
from yoke_core.domain.workflow_execution_instructions_schema import (
    ensure_workflow_execution_instructions_schema,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema


def converge_additive_schema(conn: Any) -> None:
    """Create every table, index and additive column, in FK-dependency order.

    Order matters — ``create_external_identity_tables`` FKs into actors,
    organizations (created by ``create_auth_tables``), and roles, so those
    creation steps precede it.
    """
    create_core_tables(conn)
    create_model_reference_table(conn)
    create_universe_settings_table(conn)
    apply_work_claim_scope_column(conn)
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
    create_session_control_tables(conn)
    create_decision_request_tables(conn)
    create_github_app_tables(conn)
    # QA plans bind to a concrete environment, so site/environment authority
    # must exist before the QA catalog creates that foreign key.
    create_project_registry_tables(conn)
    create_project_onboarding_tables(conn)
    create_pack_projection_tables(conn)
    create_project_structure_tables(conn)
    ensure_workflow_schema(conn)
    # Plans attach to projects, workflows and items; requirements snapshot
    # those plans, so the catalog follows all four authorities.
    create_qa_catalog_tables(conn)
    create_gate_satisfaction_tables(conn)
    # Instruction scope junctions reference workflows and projects, so the
    # instruction tables follow both authorities.
    ensure_workflow_execution_instructions_schema(conn, commit=False)
    converge_qa_plan_execution_schema(conn)
    ensure_qa_plan_review_schema(conn)
    ensure_qa_host_wait_schema(conn)
    ensure_test_machine_schema(conn)
    ensure_harness_machine_schema(conn)
    ensure_field_note_dash_promotion_schema(conn)
    ensure_doctor_runs_schema(conn)
    apply_ouroboros_columns(conn)
    ensure_ouroboros_entry_corrections_schema(conn)
    conn.commit()
    ensure_function_index(conn)
    # Strategy authority landed on prod via a since-retired governed
    # migration; fresh envs get the table from the same DDL constant
    # the strategy domain owns.
    conn.execute(STRATEGY_DOCS_CREATE_TABLE_SQL)
    conn.execute(STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL)
    ensure_strategy_execution_schema(conn)
    apply_additive_schema(conn)
    converge_flow_catalog(conn)
