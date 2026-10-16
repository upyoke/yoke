"""Run the prune command in-process against one test connection."""

from contextlib import contextmanager

from yoke_cli.commands.adapters import universe_retention as cli
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import universe_retention as handlers


def cli_on(conn, monkeypatch):
    """Route ``yoke universe prune`` passes straight to the handler on ``conn``."""

    @contextmanager
    def connect(*_args, **_kwargs):
        yield conn

    monkeypatch.setattr(db_helpers, "connect", connect)
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)

    def call(**kwargs):
        request = FunctionCallRequest(
            function=kwargs["function_id"],
            target=kwargs["target"],
            actor=kwargs["actor"],
            payload=kwargs["payload"],
        )
        outcome = handlers.handle_prune(request)
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=request.function,
            version="v1",
            request_id=request.request_id,
            result=outcome.result_payload,
            error=outcome.error,
        )

    monkeypatch.setattr(cli, "call_dispatcher", call)
