"""Code-owned registry of recurring work-claim process keys.

Defines the opening process keys and their conflict groups. ``STRATEGIZE``
and ``FEED`` share a conflict group because they operate on the same
per-project strategy authority — the ``strategy_docs`` DB table (each
project's ``.yoke/strategy/`` files are gitignored local rendered views
regenerated from the rows). The process claim is a pure process lock: it
serializes strategize/feed sessions per project and gates the
``strategy.doc.replace`` write path; it carries no linked path claims. A
project's doc corpus is its :mod:`yoke_core.domain.strategy_docs` rows
and the view location resolves via
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

from typing import Dict, Mapping

from yoke_contracts.work_processes import (
    PROCESS_DOCTOR,
    PROCESS_FEED,
    PROCESS_STRATEGIZE,
    is_known_process,
    list_processes,
)


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
        raise ValueError(f"project must be a non-empty string; got {project!r}")
    spec = _require(process_key)
    template = str(spec["conflict_group_template"])
    return template.format(project=project)


__all__ = [
    "PROCESS_FEED",
    "PROCESS_DOCTOR",
    "PROCESS_REGISTRY",
    "PROCESS_STRATEGIZE",
    "UnknownProcessError",
    "conflict_group_for",
    "is_known_process",
    "list_processes",
]
