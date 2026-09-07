"""One name per codex app-server failure, shared by every reader of one.

Two probes now speak to the same app-server — plan limits and native model
availability — and an operator comparing them has to be able to tell "this
build lacks the operation" from "the exchange broke" from "the peer refused".
Keeping the translation in one place is what stops those three from being
spelled differently depending on which probe happened to fail.
"""

from __future__ import annotations

from yoke_harness.session_relay_codex_app_server_client import CodexAppServerError


#: The client's failure codes, translated into the reason an operator reads
#: off the fleet report. An unmapped code is carried through rather than
#: collapsed into a reason that names nothing.
APP_SERVER_REASONS = {
    "binary_resolve": "cli_unavailable",
    "spawn": "app_server_spawn_failed",
    "pipes": "app_server_pipes_unavailable",
    "request_rejected": "app_server_request_rejected",
    "write_failed": "app_server_write_failed",
    "eof": "app_server_eof_before_reply",
    "timeout": "app_server_timeout",
    "response_oversize": "app_server_response_oversize",
    "stdout_unavailable": "app_server_stdout_unavailable",
    # The client raises this code only for the peer's JSON-RPC "method not
    # found" error — the one signal that actually means this build lacks
    # the operation. Every other RPC error raises "rpc_error" instead (see
    # app_server_failure_reason), so it keeps its own code rather than
    # reading as this.
    "method_error": "unsupported_on_this_build",
}


def app_server_failure_reason(failure: CodexAppServerError) -> str:
    """Name the app-server failure, keeping the class that actually raised.

    An ``rpc_error`` carries whatever code the peer's own JSON-RPC error
    named (authentication, invalid params, an internal error, …). Losing
    that code is what used to let an unrelated RPC failure read as
    "unsupported build", so it stays in the reason instead of collapsing
    into one bucket.
    """
    if failure.code == "rpc_error":
        if failure.rpc_error_code is not None:
            return f"app_server_rpc_error:{failure.rpc_error_code}"
        return "app_server_rpc_error"
    reason = APP_SERVER_REASONS.get(failure.code, f"app_server_{failure.code}")
    cause = failure.__cause__
    if cause is None or isinstance(cause, CodexAppServerError):
        return reason
    return f"{reason}:{type(cause).__name__}"


__all__ = ["APP_SERVER_REASONS", "app_server_failure_reason"]
