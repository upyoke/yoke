"""Hermetic CLI patches for the skill-recipe smoke harness."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Callable, Iterator
from unittest.mock import patch


def _call_dispatcher_stub(dispatch_stub: Callable) -> Callable:
    def _stubbed_call_dispatcher(*args, **kwargs):
        if args:
            raise TypeError("call_dispatcher smoke stub expects keyword args")
        from yoke_cli.transport.dispatcher import build_request

        request = build_request(
            function_id=kwargs["function_id"],
            target=kwargs["target"],
            payload=kwargs.get("payload"),
            options=kwargs.get("options"),
            preconditions=kwargs.get("preconditions"),
            actor=kwargs.get("actor"),
            request_id=kwargs.get("request_id"),
            intent=kwargs.get("intent"),
        )
        return dispatch_stub(request)

    return _stubbed_call_dispatcher


@contextmanager
def smoke_cli_patches(dispatch_stub: Callable) -> Iterator[None]:
    """Patch the dispatcher boundary so recipe smoke tests stay hermetic.

    Adapters are DB-free by construction under the relay contract — raw
    item refs ride the envelope target and resolve server-side inside
    ``dispatch`` — so stubbing dispatch (plus handler registration) is
    the hermetic surface. ``resolve_https_connection`` is pinned to
    ``None`` so a machine whose active env is an https connection still
    exercises the stubbed in-process path instead of relaying real
    requests to the remote dispatcher (which would both leak network
    traffic and report server-side registry state, not this checkout's).
    """
    call_stub = _call_dispatcher_stub(dispatch_stub)
    with ExitStack() as stack:
        for target in (
            "yoke_cli.commands._helpers.call_dispatcher",
            "yoke_cli.transport.dispatcher.call_dispatcher",
            "yoke_cli.commands.adapters.github_actions_wait.call_dispatcher",
            "yoke_cli.commands.adapters.github_actions_run_wait.call_dispatcher",
            "yoke_cli.commands.adapters.strategy.call_dispatcher",
            "yoke_cli.commands.adapters.strategy_create.call_dispatcher",
            "yoke_cli.commands.adapters.strategy_ops.call_dispatcher",
            "yoke_cli.commands.adapters.strategy_render.call_dispatcher",
        ):
            stack.enter_context(patch(target, side_effect=call_stub))
        stack.enter_context(patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=None,
        ))
        stack.enter_context(patch(
            "yoke_cli.commands._helpers."
            "ensure_handlers_loaded"
        ))
        yield


__all__ = ["smoke_cli_patches"]
