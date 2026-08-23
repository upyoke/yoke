"""Safe registered-CLI boundary for Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Sequence
import json
import subprocess
from typing import Any, Protocol

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)


class CommandClient(Protocol):
    def call(
        self, args: Sequence[str], *, stdin: str | None = None
    ) -> dict[str, Any]: ...


class YokeCliClient:
    """Call product-owned CLI surfaces without reflecting raw failures."""

    def call(self, args: Sequence[str], *, stdin: str | None = None) -> dict[str, Any]:
        if "--session-id" in args:
            raise AcceptanceContractError("caller_override_forbidden")
        completed = subprocess.run(
            ["yoke", *args, "--json"],
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            envelope = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AcceptanceContractError("cli_response_invalid") from exc
        if not isinstance(envelope, dict):
            raise AcceptanceContractError("cli_response_invalid")
        if completed.returncode or envelope.get("success") is not True:
            error = envelope.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            safe = (
                code
                if isinstance(code, str) and code.isidentifier()
                else "cli_call_failed"
            )
            raise AcceptanceContractError(safe)
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise AcceptanceContractError("cli_result_invalid")
        return result

    def deployed_release(self) -> dict[str, str]:
        """Return only safe release identity fields from local status."""
        completed = subprocess.run(
            ["yoke", "status", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            status = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AcceptanceContractError("status_response_invalid") from exc
        if completed.returncode or not isinstance(status, dict):
            raise AcceptanceContractError("status_call_failed")
        server = status.get("server")
        if not isinstance(server, dict) or server.get("reachable") is not True:
            raise AcceptanceContractError("server_unreachable")
        return {
            "server_build": str(server.get("build") or ""),
            "engine_version": str(server.get("engine_version") or ""),
        }


__all__ = ["CommandClient", "YokeCliClient"]
