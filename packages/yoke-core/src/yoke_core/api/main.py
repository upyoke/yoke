"""Yoke API — FastAPI control plane service.

Endpoints delegate to the shared domain layer (``yoke_core.domain``) for
lifecycle validation, board projection, approval resolution, query filtering,
deployment-run semantics, and item mutation semantics.  This module owns
HTTP-level concerns (request parsing, response serialisation, DB connections,
subprocess invocations) and defers all business logic to the domain.

Route handlers live in ``yoke_core.api.routes.*`` sub-modules; the FastAPI
app itself is built by :func:`yoke_core.api.app_factory.create_app`.

The implementation is split across responsibility-named siblings:

* :mod:`yoke_core.api.main_models` — Pydantic request/response models +
  the ``VALID_STATUSES`` / ``BOARD_COLUMN_ORDER`` lifecycle constants.
* :mod:`yoke_core.api.main_db` — legacy DB path-token resolution plus
  Postgres authority connection factories.
* :mod:`yoke_core.api.main_route_adapters` — row-to-response conversion,
  error-response envelope, FrontierState projection, and workspace to
  project resolution for route handlers.

This module is the canonical FastAPI app entry point: it re-exports the
public surface used by app startup, route modules, tests, and CLI
callers. The domain re-exports below are sourced directly from each
canonical owner sibling and avoid two-hop indirection.
"""

from __future__ import annotations

# Module-level import kept for tests that patch attributes through
# ``yoke_core.api.main`` (e.g. ``patch("yoke_core.api.main.subprocess.run")``).
import subprocess  # noqa: F401

# ---------------------------------------------------------------------------
# Sibling re-exports — Pydantic models + lifecycle constants
# ---------------------------------------------------------------------------

from yoke_core.api.main_models import (  # noqa: F401
    BOARD_COLUMN_ORDER,
    VALID_PRIORITIES,
    VALID_STATUSES,
    VALID_TYPES,
    ApproveRequest,
    ApproveResponse,
    BoardResponse,
    BoardStats,
    CapabilityRequest,
    CapabilityResponse,
    CreateItemRequest,
    ErrorDetail,
    ErrorResponse,
    FrontierItemModel,
    FrontierResultModel,
    GateEvaluationModel,
    HealthResponse,
    ItemListResponse,
    ItemObject,
    SchedulerResultModel,
    ScheduledStepModel,
    SMLStateModel,
    UpdateItemRequest,
)

from yoke_core.domain import db_backend

# ---------------------------------------------------------------------------
# Sibling re-exports — DB connection factories
# ---------------------------------------------------------------------------

from yoke_core.api.main_db import (  # noqa: F401
    _get_repo_root,
    get_config_path,
    get_db_path,
    get_db_readonly,
    get_db_readwrite,
)

# ---------------------------------------------------------------------------
# Sibling re-exports — route adapters used by route modules
# ---------------------------------------------------------------------------

from yoke_core.api.main_route_adapters import (  # noqa: F401
    _build_frontier_state,
    _error_response,
    _row_to_item,
)

# ---------------------------------------------------------------------------
# Domain re-exports — route modules and tests reach into ``main`` for
# these names. Keep direct imports from the canonical owner sibling
# and avoid two-hop indirection.
# ---------------------------------------------------------------------------

from yoke_core.domain import (  # noqa: F401
    approval,
    board,
    lifecycle,
    queries,
    runs,
)
from yoke_core.domain.approval import FlowStage, parse_flow_stages  # noqa: F401
from yoke_core.domain.dependency_planning import (  # noqa: F401
    evaluate_item_gate,
    plan_candidate_set,
)
from yoke_core.domain.drift_review_assess import (  # noqa: F401
    assess_post_delivery_drift,
)
from yoke_core.domain.frontier import (  # noqa: F401
    AdapterCategory,
    FrontierItem,
    FrontierResult,
    compute_frontier as compute_domain_frontier,
)
from yoke_core.domain.mutations import (  # noqa: F401
    SUPPORTED_UPDATE_FIELDS,
    TITLE_MAX_LENGTH,
    VALID_PRIORITIES as MUTATION_VALID_PRIORITIES,
    VALID_TYPES as MUTATION_VALID_TYPES,
    ApprovalResult,
    CreateResult,
    GateContext,
    ItemState,
    MutationResult,
    prepare_approval,
    prepare_create,
    prepare_update,
)
from yoke_core.domain.runs import DeploymentRun, find_active_run_for_item  # noqa: F401
from yoke_core.domain.scheduler import compute_schedule  # noqa: F401
from yoke_core.domain.session import (  # noqa: F401
    ClaimedWork,
    FrontierState,
    NextAction,
    SessionOffer,
    build_drift_review_failure_action,
    decide_next_action,
    should_emit_drift_review_checkpoint,
)
from yoke_core.domain.sessions import (  # noqa: F401
    SessionError,
    claim_work,
    clean_stale_harness_sessions,
    display_claim_item_id,
    emit_drift_review_completed,
    emit_next_action_chosen,
    emit_post_decision_telemetry,
    end_session,
    find_stale_sessions,
    get_claim_for_work_unit,
    handoff_claim,
    heartbeat,
    list_claims_for_session,
    list_harness_sessions,
    read_chain_checkpoint,
    reclaim_stale_session,
    register_session,
    release_all_claims,
    release_claim,
    release_item_claim_for_execution,
    resolve_claimed_work_context,
    session_offer_with_ownership,
    set_session_mode,
)
from yoke_core.api.routing_config import (  # noqa: F401
    config_path_from_db_path,
    get_max_chain_steps,
    load_routing_config,
    resolve_execution_lane,
)
from yoke_core.api.service_client import _resolve_deploy_envs  # noqa: F401
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE

# ---------------------------------------------------------------------------
# Startup gate — kept inline so monkey-patches against
# ``yoke_core.api.main.get_db_path`` take effect (the function looks up
# ``get_db_path`` through this module's namespace).
# ---------------------------------------------------------------------------

_REQUIRED_API_TABLES = ("items", STRATEGY_DOCS_TABLE)


def _startup_table_exists(conn, table_name: str) -> bool:
    if db_backend.connection_is_postgres(conn):
        row = conn.execute("SELECT to_regclass(%s)", (table_name,)).fetchone()
        return bool(row and row[0])
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_db_initialized() -> None:
    """Validate the API DB substrate before serving requests."""
    conn = get_db_readonly()
    try:
        missing = [
            table
            for table in _REQUIRED_API_TABLES
            if not _startup_table_exists(conn, table)
        ]
        if missing:
            raise RuntimeError(
                "Yoke API DB missing required table(s): "
                f"{', '.join(missing)}. Run "
                "`python3 -m yoke_core.domain.schema init` before "
                "starting the API."
            )
        _VALID = tuple(VALID_STATUSES)
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        placeholders = ",".join(p for _ in _VALID)
        cur = conn.execute(
            f"SELECT id, status FROM items WHERE status NOT IN ({placeholders})",
            _VALID,
        )
        bad_rows = cur.fetchall()
        if bad_rows:
            details = ", ".join(f"YOK-{r[0]}={r[1]}" for r in bad_rows[:10])
            raise RuntimeError(
                f"{len(bad_rows)} items have retired statuses ({details}). "
                "Run the zero-legacy DB convergence tool before starting the API."
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# App creation via factory + slim entry point
# ---------------------------------------------------------------------------

from yoke_core.api.app_factory import create_app

app = create_app()


if __name__ == "__main__":
    from yoke_core.api.server_entrypoint import main

    main()
