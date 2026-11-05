"""Bound and redact JSON-RPC failures without losing their vendor code."""

from yoke_contracts.self_host_bootstrap_output import redact_api_tokens
from yoke_harness.session_relay_codex import NativePhase

_JSONRPC_METHOD_NOT_FOUND = -32601
_RPC_ERROR_MESSAGE_MAX_CHARS = 200


class CodexAppServerError(RuntimeError):
    """The bounded app-server exchange could not prove its outcome.

    The phase is the point of the failure: an exchange that only says it
    failed leaves a stalled launch attempt with nothing to read. The code
    names the same failure for a caller that has to branch on it, so no
    reader has to match on the prose of the message.
    """

    def __init__(
        self,
        message: str,
        phase: NativePhase = "handshake",
        *,
        code: str = "unknown",
        rpc_error_code: int | str | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        # The peer's own JSON-RPC error code, when ``code`` is ``rpc_error``
        # or ``method_error`` — the detail that used to be discarded here,
        # collapsing every RPC failure into one unsupported-build reading.
        self.rpc_error_code = rpc_error_code


def _safe_rpc_message(message: object) -> str | None:
    """Bound and scrub a peer's RPC error message before it is surfaced."""
    if not isinstance(message, str):
        return None
    text = redact_api_tokens(message).strip()
    return text[:_RPC_ERROR_MESSAGE_MAX_CHARS] or None


def rpc_error(method: str, phase: NativePhase, error: object) -> CodexAppServerError:
    """Build the client's own error from the peer's JSON-RPC ``error`` object.

    Every detail the peer sent is worth keeping. Only ``-32601`` ("method
    not found") is evidence the running build genuinely lacks the operation;
    any other code is an unrelated failure — authentication, invalid
    params, an internal error, and so on — and must not be reported as one
    (field-note 46471: this branch used to collapse every peer ``error``
    into ``method_error``, so a stale credential read the same as a missing
    method).
    """
    error_code = error.get("code") if isinstance(error, dict) else None
    error_message = _safe_rpc_message(
        error.get("message") if isinstance(error, dict) else None
    )
    detail = f": {error_message}" if error_message else ""
    if error_code == _JSONRPC_METHOD_NOT_FOUND:
        return CodexAppServerError(
            f"{method} unsupported by this app-server{detail}",
            phase,
            code="method_error",
            rpc_error_code=error_code,
        )
    return CodexAppServerError(
        f"{method} failed{detail}",
        phase,
        code="rpc_error",
        rpc_error_code=error_code,
    )
