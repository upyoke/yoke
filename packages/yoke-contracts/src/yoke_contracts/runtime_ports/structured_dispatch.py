"""Core function-call interface, implemented by the service transport adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.api.function_call import ActorContext, FunctionCallResponse
from yoke_contracts.runtime_ports.loader import load_port


class StructuredDispatch(Protocol):
    """Envelope construction and transport effects supplied above domain code."""

    build_actor: Callable[..., ActorContext]
    call_dispatcher: Callable[..., FunctionCallResponse]
    emit_response: Callable[..., Any]


def get_structured_dispatch() -> StructuredDispatch:
    return cast(StructuredDispatch, load_port("structured_dispatch", StructuredDispatch))
