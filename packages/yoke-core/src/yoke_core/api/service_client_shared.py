"""Shared helpers, constants, and base utilities for the service_client sub-modules.

Thin re-export shim — the implementation is split across responsibility-named
siblings:

* :mod:`yoke_core.api.service_client_shared_io` — repo root, subprocess
  PYTHONPATH, SQLite connection factories, routing-config loader.
* :mod:`yoke_core.api.service_client_shared_session_resolver` — session-ID
  auto-resolution, ``YOK-N`` argument parsing, shell-wrapper mode flag,
  ``YOKE_ROOT`` normalization, isolated-test mutation guard.
* :mod:`yoke_core.api.service_client_shared_done_ceremony` — done-transition
  nonce verification, operator recovery prompt, in-process recovery driver.
* :mod:`yoke_core.api.service_client_shared_emit` — mutation result
  serialisation and shell/JSON dual-mode output emitter.
* :mod:`yoke_core.api.service_client_shared_gate_context` — item-state
  loading, schema introspection, gate-context assembly.

Plus the domain re-exports (``approval``, ``mutations``, ``runs``,
``compute_domain_frontier``, ``evaluate_item_gate``, the session
helpers, etc.) every other ``service_client_*`` module imports from
this module path. The shim re-exports the whole public surface for
``from yoke_core.api.service_client_shared import ...`` callers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Sibling re-exports — connection factories and IO infrastructure
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_shared_io import (  # noqa: F401
    _get_config_path,
    _get_db_path,
    _get_db_readonly,
    _get_db_readwrite,
    _load_routing_config,
    _repo_root,
    _subprocess_backend_env,
    _subprocess_pythonpath,
    _subprocess_service_env,
)

# ---------------------------------------------------------------------------
# Sibling re-exports — session-ID resolution and CLI argument helpers
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_shared_session_resolver import (  # noqa: F401
    SESSION_REQUIRED_ERROR,
    _isolated_test_mutation_error,
    _normalize_yoke_root,
    _parse_item_id_arg,
    _resolve_session_id,
    _shell_wrapper_mode,
)

# ---------------------------------------------------------------------------
# Sibling re-exports — done-transition nonce + recovery
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_shared_done_ceremony import (  # noqa: F401
    _confirm_done_recovery,
    _consume_done_nonce,
    _run_done_recovery,
    _update_requests_done,
)

# ---------------------------------------------------------------------------
# Sibling re-exports — mutation result + backlog-result emission
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_shared_emit import (  # noqa: F401
    _emit_backlog_result,
    _mutation_result_to_dict,
)

# ---------------------------------------------------------------------------
# Sibling re-exports — item-state loader, schema probes, gate context
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_shared_gate_context import (  # noqa: F401
    _load_gate_context,
    _load_item_state,
    _resolve_deploy_envs,
    _table_exists,
)

# ---------------------------------------------------------------------------
# Domain re-exports — every service_client_*.py module reaches into
# `service_client_shared` for these names. Keep direct imports from the
# canonical owner sibling and avoid two-hop indirection.
# ---------------------------------------------------------------------------

from yoke_core.domain import (  # noqa: F401
    approval,
    board,
    lifecycle,
    mutations,
    queries,
    runs,
)
from yoke_core.domain.session import (  # noqa: F401
    ClaimedWork,
    FrontierState,
    SessionOffer,
    build_drift_review_failure_action,
    decide_next_action,
    should_emit_drift_review_checkpoint,
)
from yoke_core.domain.sessions import (  # noqa: F401
    SessionError,
    display_claim_item_id,
    emit_drift_review_completed,
    emit_next_action_chosen,
    emit_post_decision_telemetry,
    heartbeat as domain_heartbeat,
    end_session as domain_end_session,
    end_session_if_empty as domain_end_session_if_empty,
    clean_stale_harness_sessions as domain_clean_stale,
    normalize_claim_item_id,
    read_chain_checkpoint,
    read_chain_checkpoint as domain_read_checkpoint,
    release_claims_for_done_item as domain_release_done_claims,
    release_item_claim_for_execution,
    resolve_claimed_work_context,
    session_offer_with_ownership,
    set_session_mode,
    update_chain_checkpoint as domain_update_checkpoint,
)
from yoke_core.domain.frontier import (  # noqa: F401
    AdapterCategory,
    FrontierItem,
    FrontierResult,
    compute_frontier as compute_domain_frontier,
)
from yoke_core.domain.drift_review_assess import (  # noqa: F401
    assess_post_delivery_drift,
)
from yoke_core.domain.scheduler import compute_schedule  # noqa: F401
from yoke_core.domain.dependency_planning import (  # noqa: F401
    evaluate_item_gate,
    plan_candidate_set,
)
from yoke_core.api.routing_config import (  # noqa: F401
    config_path_from_db_path,
    get_max_chain_steps,
    load_routing_config,
    resolve_execution_lane,
)
