"""Safe registered-CLI boundary for Fleet live acceptance."""

from __future__ import annotations

from collections.abc import Sequence
import json
import subprocess
import time
from typing import Any, Callable, Protocol

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from yoke_core.domain.session_liveness_pump import HEARTBEAT_INTERVAL_SECONDS


class CommandClient(Protocol):
    def call(
        self, args: Sequence[str], *, stdin: str | None = None
    ) -> dict[str, Any]: ...


class AcceptanceOwnerKeepalive:
    """Keep only the authenticated top-level acceptance owner live."""

    def __init__(
        self,
        client: CommandClient,
        *,
        owner_session_id: str,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.client = client
        self.owner_session_id = owner_session_id
        self.sleep = sleep
        self.monotonic = monotonic
        self.interval = float(interval_seconds)
        if self.interval <= 0:
            raise ValueError("interval_seconds must be positive")
        self.last_touch = monotonic()

    def touch(self) -> None:
        """Refresh ambient ownership; never accept a caller-selected identity."""
        result = self.client.call(["sessions", "touch"])
        session = result.get("session")
        if (
            not isinstance(session, dict)
            or session.get("session_id") != self.owner_session_id
        ):
            raise AcceptanceContractError("acceptance_owner_touch_mismatch")
        self.last_touch = self.monotonic()

    def tick(self) -> None:
        if self.monotonic() - self.last_touch >= self.interval:
            self.touch()

    def call(self, args: Sequence[str], *, stdin: str | None = None) -> dict[str, Any]:
        """Refresh when due, then preserve the registered CLI boundary."""
        self.tick()
        return self.client.call(args, stdin=stdin)

    def wait(self, seconds: float) -> None:
        """Bound a polling wait so owner liveness cannot develop a blind spot."""
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            chunk = min(self.interval, remaining)
            self.sleep(chunk)
            remaining -= chunk
            self.tick()


class _OwnerQualification:
    def __init__(self, owner: AcceptanceOwnerKeepalive, qualification: Any) -> None:
        self.owner = owner
        self.qualification = qualification

    def open(self, *args: Any, **kwargs: Any) -> Any:
        self.owner.touch()
        return self.qualification.open(*args, **kwargs)

    def verify(self, *args: Any, **kwargs: Any) -> Any:
        return self.qualification.verify(*args, **kwargs)


def bind_acceptance_owner(
    client: CommandClient,
    owner_session_id: str,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    qualification: Any | None,
) -> tuple[CommandClient, Callable[[float], None], Any | None]:
    """Activate ambient owner liveness and guard qualification boundaries."""
    owner = AcceptanceOwnerKeepalive(
        client,
        owner_session_id=owner_session_id,
        sleep=sleep,
        monotonic=monotonic,
    )
    owner.touch()
    guarded = _OwnerQualification(owner, qualification) if qualification else None
    return owner, owner.wait, guarded


class YokeCliClient:
    """Call product-owned CLI surfaces without reflecting raw failures."""

    def __init__(self, *, explicit_env: str | None = None) -> None:
        self.explicit_env = str(explicit_env or "").strip() or None

    def _command(self, args: Sequence[str]) -> list[str]:
        prefix = ["yoke"]
        if self.explicit_env:
            prefix.extend(("--env", self.explicit_env))
        return [*prefix, *args]

    def call(self, args: Sequence[str], *, stdin: str | None = None) -> dict[str, Any]:
        if (
            "--session-id" in args
            or "--env" in args
            or any(str(token).startswith("--env=") for token in args)
        ):
            raise AcceptanceContractError("caller_override_forbidden")
        completed = subprocess.run(
            self._command([*args, "--json"]),
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
            self._command(["status", "--json"]),
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


__all__ = [
    "AcceptanceOwnerKeepalive",
    "CommandClient",
    "YokeCliClient",
    "bind_acceptance_owner",
]
