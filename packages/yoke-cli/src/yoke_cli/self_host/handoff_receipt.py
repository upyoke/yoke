"""Host side of the first-boot handoff: save the token or name the failure."""

from __future__ import annotations

import json
from pathlib import Path
import select
import subprocess

from yoke_cli.self_host import first_boot_token, protection
from yoke_cli.self_host.diagnostics import handoff_failure_details
from yoke_cli.self_host.runtime_errors import SelfHostRuntimeError, refuse
from yoke_contracts import terminal_detached_process
from yoke_contracts.self_host_bootstrap_output import is_api_token
from yoke_contracts.self_host_handoff import (
    HANDOFF_ACK,
    HANDOFF_CLIENT_MODULE,
    HANDOFF_FAILURES,
    HANDOFF_TIMEOUT_SECONDS,
)

#: The client's own deadline expires first, so its named class arrives first.
RECEIPT_TIMEOUT_SECONDS = HANDOFF_TIMEOUT_SECONDS + 15
_CORE_LOGS = "read the bootstrap refusal with `docker compose logs core` and repair it"
RECOVERIES = {
    "self_host_handoff_connect_timeout": (
        "the core bootstrap never opened its handoff socket; " + _CORE_LOGS
    ),
    "self_host_handoff_bootstrap_closed": (
        "the core bootstrap closed the handoff before delivering a token; " + _CORE_LOGS
    ),
    "self_host_handoff_ack_missing": (
        "the core never received this host's token-saved acknowledgment, so "
        "it did not start serving; " + _CORE_LOGS
    ),
    "self_host_handoff_unhealthy_timeout": (
        f"the core server did not report healthy within {HANDOFF_TIMEOUT_SECONDS} "
        "seconds; read `docker compose logs core db` for the startup or "
        "database refusal and repair it"
    ),
    "self_host_handoff_timeout": (
        f"the core sent no handoff receipt within {RECEIPT_TIMEOUT_SECONDS} "
        "seconds; " + _CORE_LOGS
    ),
    "self_host_handoff_exec_failed": (
        "`docker compose exec` into the core container failed before any "
        "receipt; check the core container state in the details and "
        "`docker compose logs core`"
    ),
    "self_host_handoff_receipt_invalid": (
        "the core returned a receipt this CLI does not recognize; confirm the "
        "bundle's core image matches this CLI with `yoke self-host upgrade`"
    ),
    "self_host_handoff_token_invalid": (
        "the core returned a malformed first-boot token; confirm the bundle's "
        "core image matches this CLI with `yoke self-host upgrade`"
    ),
    "self_host_handoff_token_store_failed": (
        "this host could not durably save the first-boot token; repair the "
        "bundle's secrets directory permissions and free space"
    ),
}
_RECEIPTS = ({"healthy": False, "paused": True}, {"healthy": True})


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _parse(line: bytes):
    try:
        return json.loads(line)
    except ValueError:
        raise _Refused("self_host_handoff_receipt_invalid") from None


def _failure_reason(stdout: bytes) -> str | None:
    """The reason a closed ``{"error": CLASS}`` line on *stdout* names, if any."""
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and "error" in payload:
            failure = payload["error"]
            if failure in HANDOFF_FAILURES:
                return f"self_host_handoff_{failure}"
            return "self_host_handoff_receipt_invalid"
    return None


def _save_token(directory: Path, token) -> None:
    if not isinstance(token, str) or not is_api_token(token):
        raise _Refused("self_host_handoff_token_invalid")
    try:
        target = first_boot_token.token_drop_path(directory)
        if target.exists():
            first_boot_token.require_token_drop(directory)
        protection.atomic_replace_bytes(target, (token + "\n").encode(), mode=0o600)
    except (
        OSError,
        protection.SelfHostProtectionError,
        first_boot_token.FirstBootTokenError,
    ):
        raise _Refused("self_host_handoff_token_store_failed") from None


def _exchange(process, directory: Path, header: bytes) -> tuple[dict | None, bytes]:
    """Run the handoff: (receipt or None when the exec ended early, first line)."""
    try:
        process.stdin.write(header)
        process.stdin.flush()
    except OSError:
        return None, b""
    if not select.select([process.stdout], [], [], RECEIPT_TIMEOUT_SECONDS)[0]:
        raise _Refused("self_host_handoff_timeout")
    line = process.stdout.readline(1024)
    if not line:
        return None, line
    result = _parse(line)
    if not isinstance(result, dict) or "error" in result:
        return None, line
    if "token" in result:
        _save_token(directory, result["token"])
        try:
            process.stdin.write(HANDOFF_ACK)
            process.stdin.flush()
        except OSError:
            return None, line
        return {"healthy": True}, line
    if result not in _RECEIPTS:
        raise _Refused("self_host_handoff_receipt_invalid")
    return result, line


def receive_token(directory: Path, executable: str, header: bytes) -> dict:
    """Durably save a minted token, or refuse with the client's named class."""
    command = (executable, "compose", "exec", "-T", "--user", "0", "core")
    command += ("python", "-m", HANDOFF_CLIENT_MODULE)
    process, stderr = None, b""
    try:
        try:
            process = terminal_detached_process.popen(
                command,
                cwd=directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError:
            raise _Refused("self_host_handoff_exec_failed") from None
        receipt, stdout = _exchange(process, directory, header)
        try:
            rest, stderr = process.communicate(timeout=RECEIPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise _Refused("self_host_handoff_timeout") from None
        stdout += rest
        if receipt is not None and not process.returncode:
            return receipt
        raise _Refused(
            _failure_reason(stdout)
            or (
                "self_host_handoff_exec_failed"
                if process.returncode
                else "self_host_handoff_receipt_invalid"
            )
        )
    except _Refused as refused:
        if process is not None and process.poll() is None:
            process.kill()
            _, late = process.communicate()
            stderr += late
        code = "unavailable" if process is None else process.returncode
        raise _refusal(refused.reason, directory, executable, code, stderr) from None


def _refusal(reason, directory, executable, code, stderr) -> SelfHostRuntimeError:
    details = handoff_failure_details(directory, executable, code, stderr)
    return refuse(reason, directory, RECOVERIES[reason], details)
