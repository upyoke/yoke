"""Code-owned registry of recurring work-claim process keys.

Defines the opening process keys and their conflict groups. ``STRATEGIZE``
and ``FEED`` share a conflict group because they operate on the same
per-project strategy authority — the ``strategy_docs`` DB table (each
project's ``.yoke/strategy/`` files are tracked rendered views). The
process claim is a pure process lock: it serializes strategize/feed
sessions per project and gates the ``strategy.doc.replace`` write path;
it carries no linked path claims. Main-checkout commits of the rendered
views authorize via the matches-the-master freshness rule in
:mod:`yoke_core.domain.lint_main_commit_process_claims`; a project's
doc corpus is its :mod:`yoke_core.domain.strategy_docs` rows and the
view location resolves via
:mod:`yoke_core.domain.strategy_docs_paths`. ``DOCTOR`` has its own
project-scoped group.

Process target semantics:

- ``conflict_group`` is computed from the process key and project.
  STRATEGIZE and FEED on project=yoke share the group
  ``strategy-control-plane:yoke`` and cannot run simultaneously.
- Multiple projects may run the same process concurrently — the
  conflict group includes the project as scope.
"""

from __future__ import annotations

from typing import Dict, List, Mapping

PROCESS_STRATEGIZE = "STRATEGIZE"
PROCESS_FEED = "FEED"
PROCESS_DOCTOR = "DOCTOR"


# Map a NextAction action-value to the registered process key consumed
# by ProcessOfferPolicy. The map is intentionally small — adding a
# future process means appending the registry entry
# above and (when the action surfaces in decide_next_action) the
# matching mapping here. Unknown action values return ``None`` so the
# gate is a no-op for non-process actions like RESUME/CHARGE/WAIT.
_ACTION_KIND_TO_PROCESS_KEY: Dict[str, str] = {
    "strategize": PROCESS_STRATEGIZE,
    "feed": PROCESS_FEED,
    # ``DOCTOR`` is registered as a process key but is not yet a
    # NextAction kind in ``decide_next_action``; the entry is added
    # here once the decision engine starts producing it.
}

_STRATEGY_CONTROL_PLANE_GROUP_TEMPLATE = "strategy-control-plane:{project}"
_DOCTOR_GROUP_TEMPLATE = "doctor:{project}"

# Frozen at import time. Operators add a new process by appending here
# and writing a matching test.
PROCESS_REGISTRY: Mapping[str, Dict[str, object]] = {
    PROCESS_STRATEGIZE: {
        "conflict_group_template": _STRATEGY_CONTROL_PLANE_GROUP_TEMPLATE,
    },
    PROCESS_FEED: {
        "conflict_group_template": _STRATEGY_CONTROL_PLANE_GROUP_TEMPLATE,
    },
    PROCESS_DOCTOR: {
        "conflict_group_template": _DOCTOR_GROUP_TEMPLATE,
    },
}


class UnknownProcessError(KeyError):
    """Raised when a caller references a process key not in the registry."""


def list_processes() -> List[str]:
    """Return the opening canon of registered process keys."""
    return list(PROCESS_REGISTRY.keys())


def is_known_process(process_key: str) -> bool:
    return process_key in PROCESS_REGISTRY


def _require(process_key: str) -> Dict[str, object]:
    if process_key not in PROCESS_REGISTRY:
        raise UnknownProcessError(
            f"unknown process key {process_key!r}; known keys: "
            f"{sorted(PROCESS_REGISTRY)}"
        )
    return dict(PROCESS_REGISTRY[process_key])


def conflict_group_for(process_key: str, project: str) -> str:
    """Compute the conflict-group string for ``process_key`` on ``project``.

    Two distinct process keys whose templates resolve to the same string
    on the same project cannot run concurrently — that is the entire
    point of the shared group ``strategy-control-plane:<project>``
    backing STRATEGIZE and FEED.
    """
    if not project or not str(project).strip():
        raise ValueError(
            f"project must be a non-empty string; got {project!r}"
        )
    spec = _require(process_key)
    template = str(spec["conflict_group_template"])
    return template.format(project=project)


def action_kind_to_process_key(action_value: str) -> "str | None":
    """Return the registered process key for a ``NextAction`` action value.

    ``ProcessOfferPolicy`` is keyed on the registered process key
    (``STRATEGIZE``, ``FEED``, ``DOCTOR``); the decision engine
    returns a ``NextAction`` with an ``ActionKind``
    enum value (``"strategize"``, ``"feed"``, ...). This helper bridges
    the two so callers do not hard-code the mapping inline.

    Returns ``None`` when ``action_value`` is not a known process action
    — non-process actions like ``RESUME`` / ``CHARGE`` / ``WAIT`` /
    ``ESCALATE`` flow through the gate untouched.
    """
    if not action_value:
        return None
    return _ACTION_KIND_TO_PROCESS_KEY.get(str(action_value).strip().lower())


# Path-token vocabulary for process actions in lane allowlists. Sibling
# to ``_NEXT_STEP_TO_PATH`` in ``session_decision_charge.py`` /
# ``sessions_analytics_core.py``: those map scheduler ``next_step``
# values to lifecycle path tokens; this map covers process actions a
# lane allowlist may opt into. ``DOCTOR`` is recognized as a valid
# token even though it is not yet a ``NextAction`` kind; documentation
# and config validation rely on the expanded vocabulary.
_PROCESS_KEY_TO_PATH: Dict[str, str] = {
    PROCESS_STRATEGIZE: "strategize",
    PROCESS_FEED: "feed",
    PROCESS_DOCTOR: "doctor",
}


def process_key_to_path(process_key: str) -> "str | None":
    """Return the lane-policy path token for a registered process key.

    Returns ``None`` for empty or unknown keys so callers can short-
    circuit without raising. Non-process actions never reach this map
    in the gate flow because :func:`action_kind_to_process_key` filters
    them upstream.
    """
    if not process_key:
        return None
    return _PROCESS_KEY_TO_PATH.get(str(process_key).strip().upper())


__all__ = [
    "PROCESS_FEED",
    "PROCESS_DOCTOR",
    "PROCESS_REGISTRY",
    "PROCESS_STRATEGIZE",
    "UnknownProcessError",
    "action_kind_to_process_key",
    "conflict_group_for",
    "is_known_process",
    "list_processes",
    "process_key_to_path",
]
