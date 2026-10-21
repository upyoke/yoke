"""Resolve a QA execution's subject once per function request.

Permission, claim verification, the handler's target check and settlement
each need the same run/stage/member subject. Each resolution reads the run's
frozen stage, its members and their plan attachments, so a request that
resolved it four times did four times that work. Inside one dispatched
request for an existing execution, the first resolution is shared with the
later ones, across their separate connections.

Only requests that name an existing execution share answers: their subject
comes from the execution's immutable target, which the request cannot
change. Materialization and begin create the rows a shared group is resolved
from, so they and every other function resolve afresh each time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from typing import Any, TypeVar

_SUBJECTS: ContextVar[dict | None] = ContextVar("qa_request_subjects", default=None)

#: Functions that act on an existing execution and resolve its subject.
EXECUTION_SUBJECT_FUNCTIONS = frozenset(
    {
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.pause",
        "qa.plan_execution.resume",
        "qa.plan_execution.advance",
        "qa.plan_execution.complete",
        "qa.plan_execution.abort",
        "qa.plan_execution.adopt",
        "qa.plan_review.begin",
        "qa.plan_review.submit",
    }
)

Value = TypeVar("Value")


def _function_id(request: Any) -> str:
    if isinstance(request, Mapping):
        return str(request.get("function") or "")
    return str(getattr(request, "function", "") or "")


def request_subject_scope(dispatch: Callable[..., Value]) -> Callable[..., Value]:
    """Share subject answers within one dispatched execution request.

    Every other request, including one dispatched from inside a handler,
    starts with sharing off, so no answer outlives or crosses its request.
    """

    @wraps(dispatch)
    def run(request: Any, *args: Any, **kwargs: Any) -> Value:
        shared = _function_id(request) in EXECUTION_SUBJECT_FUNCTIONS
        token = _SUBJECTS.set({} if shared else None)
        try:
            return dispatch(request, *args, **kwargs)
        finally:
            _SUBJECTS.reset(token)

    return run


def _remember(key: Callable[[], tuple], read: Callable[[], Value]) -> Value:
    cache = _SUBJECTS.get()
    if cache is None:
        return read()
    key = key()
    if key not in cache:
        cache[key] = read()
    return deepcopy(cache[key])


def execution_subject_once(
    execution: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    require_active: bool,
    read: Callable[[bool], dict],
) -> dict:
    """The subject behind one execution target, read once per request.

    An answer that passed the active-stage check also serves a caller that
    does not require it; the reverse never holds.
    """
    cache = _SUBJECTS.get()
    if cache is None:
        return read(require_active)
    identity = (
        "execution_subject",
        str(execution.get("deployment_run_id") or ""),
        str(execution.get("deployment_stage") or ""),
        execution.get("deployment_member_item_id"),
        json.dumps(dict(target), sort_keys=True, default=str),
    )
    active = (*identity, True)
    key = active if require_active or active in cache else (*identity, False)
    if key not in cache:
        cache[key] = read(require_active)
    return deepcopy(cache[key])


def run_subject_once(request: Any, read: Callable[[], Value]) -> Value:
    """The (project, slug, member) a request's run QA subject names, once."""
    return _remember(
        lambda: (
            "run_subject",
            request.function,
            request.target.model_dump_json(),
            json.dumps(request.payload or {}, sort_keys=True, default=str),
        ),
        read,
    )


__all__ = [
    "EXECUTION_SUBJECT_FUNCTIONS",
    "execution_subject_once",
    "request_subject_scope",
    "run_subject_once",
]
