"""Machine QA refusal outcomes shared by domain operations."""

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )
