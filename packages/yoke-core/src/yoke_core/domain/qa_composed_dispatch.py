"""Scoped dispatcher override for one authorized composed QA action.

Ordinary case execution uses the registered function dispatcher for every
read and write. A doorman-facing case action has already crossed its own
permission boundary, so its internal run/artifact legs may call the same
handlers without requiring a separate harness work claim. The override is a
context-local callback installed only while that composed action executes;
all CLI and harness execution continues through the normal dispatcher.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    TargetRef,
)


QaDispatch = Callable[
    [str, TargetRef, dict[str, Any], Optional[ActorContext]],
    FunctionCallResponse,
]

_COMPOSED_DISPATCH: ContextVar[Optional[QaDispatch]] = ContextVar(
    "qa_composed_dispatch",
    default=None,
)


def call_qa_function(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[dict[str, Any]] = None,
    actor: Optional[ActorContext] = None,
) -> FunctionCallResponse:
    """Call a QA function through the active composed or normal dispatcher."""
    body = dict(payload or {})
    override = _COMPOSED_DISPATCH.get()
    if override is not None:
        return override(function_id, target, body, actor)

    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=target,
        payload=body,
        actor=actor,
    )


@contextmanager
def composed_qa_dispatch(
    dispatch_call: QaDispatch,
) -> Iterator[None]:
    """Install one context-local dispatcher for an authorized composition."""
    token = _COMPOSED_DISPATCH.set(dispatch_call)
    try:
        yield
    finally:
        _COMPOSED_DISPATCH.reset(token)


__all__ = [
    "QaDispatch",
    "call_qa_function",
    "composed_qa_dispatch",
]
