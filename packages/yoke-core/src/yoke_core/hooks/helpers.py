"""Thin re-export shim for the hook-helper sibling modules.

Each public name is re-exported here directly from the sibling that
owns it — never two-hop through an intermediate sibling — so legacy
``from yoke_core.hooks.helpers import ...`` callers continue to
resolve. Active sibling owners:

- :mod:`yoke_core.hooks.helpers_session_id` — project-root, DB override,
  session ID, dispatch context, hook-JSON parsing.
- :mod:`yoke_core.hooks.helpers_markers` — current-item / done-item
  marker primitives.
- :mod:`yoke_core.hooks.helpers_identity` — executor / provider /
  predicate / entrypoint detection.
- :mod:`yoke_core.hooks.helpers_model` — requested-model detection
  (transcript walk + ``--model`` argv parsing).
"""

from __future__ import annotations

from yoke_core.hooks.helpers_identity import (  # noqa: F401
    _compose_executor,
    _normalize_surface_token,
    canonical_harness_id,
    compose_executor_from_entrypoint,
    detect_entrypoint,
    detect_executor,
    detect_native_thread_id,
    detect_provider,
    is_claude,
    is_codex,
)
from yoke_core.hooks.helpers_markers import (  # noqa: F401
    CURRENT_ITEM_MARKER,
    DEFAULT_DONE_MARKER_MAX_AGE,
    DONE_ITEM_MARKER,
    read_current_item_marker,
    read_done_item_marker,
    write_current_item_marker,
    write_done_item_marker,
)
from yoke_core.hooks.helpers_model import (  # noqa: F401
    _PLACEHOLDER_MODEL_VALUES,
    _extract_model_from_argv,
    _is_placeholder_model,
    _read_parent_argv,
    detect_requested_model,
)
from yoke_core.hooks.helpers_session_id import (  # noqa: F401
    BUSY_TIMEOUT_MS,
    find_project_root,
    get_session_id,
    parse_hook_json,
    resolve_dispatch_context,
    resolve_yoke_db,
)


__all__ = [
    "BUSY_TIMEOUT_MS",
    "CURRENT_ITEM_MARKER",
    "DEFAULT_DONE_MARKER_MAX_AGE",
    "DONE_ITEM_MARKER",
    "canonical_harness_id",
    "compose_executor_from_entrypoint",
    "detect_entrypoint",
    "detect_executor",
    "detect_requested_model",
    "detect_native_thread_id",
    "detect_provider",
    "find_project_root",
    "get_session_id",
    "is_claude",
    "is_codex",
    "parse_hook_json",
    "read_current_item_marker",
    "read_done_item_marker",
    "resolve_dispatch_context",
    "resolve_yoke_db",
    "write_current_item_marker",
    "write_done_item_marker",
]
