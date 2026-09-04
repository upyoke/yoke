"""Wire contract for the machine-local resident hook evaluator."""

from __future__ import annotations

import json
import socket
import struct
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
RESIDENT_IDLE_TIMEOUT_SECONDS = 600
EVALUATOR_PAYLOAD_KEY = "yoke_hook_evaluator"
HOOK_OBSERVATION_BATCH_CAPABILITY = "read_only_observation_batch_v1"
HOOK_CLIENT_WALL_CAPABILITY = "hook_client_wall_v1"
HOOK_CLIENT_WALL_BATCH_FIELD = "client_wall_reports"
HOOK_CLIENT_WALL_PATH = "/v1/hooks/telemetry/client-wall"
# Correlation key the hook client mints for its own dispatch. It travels in
# the telemetry context and is copied into the indexed ``events`` column of
# the same name, which is how the completing wall-time report finds its row.
HOOK_CLIENT_TIMING_ID_FIELD = "client_timing_id"
HOOK_EVALUATOR_CAPABILITIES = (
    HOOK_OBSERVATION_BATCH_CAPABILITY,
    HOOK_CLIENT_WALL_CAPABILITY,
)
HOOK_MODEL_CONFIRMATION_FIELD = "model_confirmation"
HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD = "model_confirmations"
EVALUATORS = frozenset({"resident", "inprocess"})


class HookEvaluatorProtocolError(RuntimeError):
    """A local evaluator peer sent a malformed or oversized frame."""


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise HookEvaluatorProtocolError(f"{field} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HookEvaluatorProtocolError(
            f"{field} must be a positive integer"
        ) from None
    if parsed <= 0:
        raise HookEvaluatorProtocolError(f"{field} must be a positive integer")
    return parsed


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise HookEvaluatorProtocolError(f"{field} must be a string")
    return value


def _event_id(value: Any) -> str:
    raw = _string(value, "event_id")
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        raise HookEvaluatorProtocolError("event_id must be a UUID") from None
    return str(parsed)


@dataclass(frozen=True)
class HookClientWallReport:
    """Completion report sent by the short-lived client to its resident."""

    event_id: str
    client_wall_ms: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "kind": "client_wall",
            "event_id": self.event_id,
            "client_wall_ms": self.client_wall_ms,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "HookClientWallReport":
        if not isinstance(value, Mapping) or value.get("protocol") != PROTOCOL_VERSION:
            raise HookEvaluatorProtocolError("client wall report protocol is invalid")
        if value.get("kind") != "client_wall":
            raise HookEvaluatorProtocolError("client wall report kind is invalid")
        raw_ms = value.get("client_wall_ms")
        if isinstance(raw_ms, bool):
            raise HookEvaluatorProtocolError("client_wall_ms must be an integer")
        try:
            elapsed = int(raw_ms)
        except (TypeError, ValueError):
            raise HookEvaluatorProtocolError(
                "client_wall_ms must be an integer"
            ) from None
        if elapsed < 0 or elapsed > 600_000:
            raise HookEvaluatorProtocolError(
                "client_wall_ms is outside the supported range"
            )
        return cls(event_id=_event_id(value.get("event_id")), client_wall_ms=elapsed)


@dataclass(frozen=True)
class HookEvaluatorRequest:
    """One hook invocation plus the originating process context."""

    event_name: str
    stdin: str
    dry_run: bool
    pid: int
    ppid: int
    cwd: str
    environment: dict[str, str]
    revision: str
    client_timing_id: str = ""

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "event_name": self.event_name,
            "stdin": self.stdin,
            "dry_run": self.dry_run,
            "pid": self.pid,
            "ppid": self.ppid,
            "cwd": self.cwd,
            "environment": self.environment,
            "revision": self.revision,
            "client_timing_id": self.client_timing_id,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "HookEvaluatorRequest":
        if not isinstance(value, Mapping):
            raise HookEvaluatorProtocolError("request must be an object")
        if value.get("protocol") != PROTOCOL_VERSION:
            raise HookEvaluatorProtocolError(
                f"unsupported hook evaluator protocol {value.get('protocol')!r}"
            )
        raw_environment = value.get("environment")
        if not isinstance(raw_environment, Mapping) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in raw_environment.items()
        ):
            raise HookEvaluatorProtocolError(
                "environment must contain only string keys and values"
            )
        dry_run = value.get("dry_run")
        if not isinstance(dry_run, bool):
            raise HookEvaluatorProtocolError("dry_run must be a boolean")
        raw_timing_id = value.get("client_timing_id")
        timing_id = "" if raw_timing_id in (None, "") else _event_id(raw_timing_id)
        return cls(
            event_name=_string(value.get("event_name"), "event_name"),
            stdin=_string(value.get("stdin"), "stdin"),
            dry_run=dry_run,
            pid=_positive_int(value.get("pid"), "pid"),
            ppid=_positive_int(value.get("ppid"), "ppid"),
            cwd=_string(value.get("cwd"), "cwd"),
            environment=dict(raw_environment),
            revision=_string(value.get("revision"), "revision"),
            client_timing_id=timing_id,
        )


def encode_frame(payload: Mapping[str, Any]) -> bytes:
    try:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HookEvaluatorProtocolError("frame is not JSON serializable") from exc
    if len(body) > MAX_FRAME_BYTES:
        raise HookEvaluatorProtocolError(f"frame exceeds {MAX_FRAME_BYTES} byte limit")
    return struct.pack("!I", len(body)) + body


def send_frame(peer: socket.socket, payload: Mapping[str, Any]) -> None:
    peer.sendall(encode_frame(payload))


def _receive_exact(peer: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = peer.recv(remaining)
        if not chunk:
            raise HookEvaluatorProtocolError("peer closed before frame completed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def receive_frame(peer: socket.socket) -> dict[str, Any]:
    header = _receive_exact(peer, 4)
    size = struct.unpack("!I", header)[0]
    if size > MAX_FRAME_BYTES:
        raise HookEvaluatorProtocolError(f"frame exceeds {MAX_FRAME_BYTES} byte limit")
    try:
        decoded = json.loads(_receive_exact(peer, size).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HookEvaluatorProtocolError("frame is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise HookEvaluatorProtocolError("frame must contain an object")
    return decoded


def attach_evaluator_metadata(
    stdin_data: str,
    *,
    evaluator: str,
    warm_duration_ms: int,
    fallback_reason: str = "",
    client_timing_id: str = "",
) -> str:
    """Add evaluator facts without changing any hook policy field."""
    try:
        payload = json.loads(stdin_data) if stdin_data else {}
    except (TypeError, ValueError):
        return stdin_data
    if not isinstance(payload, dict) or evaluator not in EVALUATORS:
        return stdin_data
    metadata: dict[str, Any] = {
        "evaluator": evaluator,
        "warm_duration_ms": max(0, int(warm_duration_ms)),
    }
    if client_timing_id:
        try:
            metadata[HOOK_CLIENT_TIMING_ID_FIELD] = _event_id(client_timing_id)
        except HookEvaluatorProtocolError:
            pass
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason
    payload[EVALUATOR_PAYLOAD_KEY] = metadata
    return json.dumps(payload, separators=(",", ":"))


def evaluator_telemetry_fields(payload: Any) -> dict[str, Any]:
    """Validated fields copied into ``HookDispatchTelemetry`` context."""
    if not isinstance(payload, Mapping):
        return {}
    metadata = payload.get(EVALUATOR_PAYLOAD_KEY)
    if not isinstance(metadata, Mapping):
        return {}
    evaluator = metadata.get("evaluator")
    if evaluator not in EVALUATORS:
        return {}
    try:
        warm_duration_ms = max(0, int(metadata.get("warm_duration_ms", 0)))
    except (TypeError, ValueError):
        warm_duration_ms = 0
    fields: dict[str, Any] = {
        "evaluator": evaluator,
        "resident_warm_duration_ms": (
            warm_duration_ms if evaluator == "resident" else 0
        ),
    }
    try:
        fields[HOOK_CLIENT_TIMING_ID_FIELD] = _event_id(
            metadata.get(HOOK_CLIENT_TIMING_ID_FIELD)
        )
    except HookEvaluatorProtocolError:
        pass
    fallback_reason = metadata.get("fallback_reason")
    if evaluator == "inprocess" and isinstance(fallback_reason, str):
        fields["evaluator_fallback_reason"] = fallback_reason[:240]
    return fields


__all__ = [
    "EVALUATOR_PAYLOAD_KEY",
    "HOOK_CLIENT_TIMING_ID_FIELD",
    "HOOK_CLIENT_WALL_BATCH_FIELD",
    "HOOK_CLIENT_WALL_CAPABILITY",
    "HOOK_CLIENT_WALL_PATH",
    "HOOK_EVALUATOR_CAPABILITIES",
    "HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD",
    "HOOK_MODEL_CONFIRMATION_FIELD",
    "HOOK_OBSERVATION_BATCH_CAPABILITY",
    "HookClientWallReport",
    "HookEvaluatorProtocolError",
    "HookEvaluatorRequest",
    "MAX_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "RESIDENT_IDLE_TIMEOUT_SECONDS",
    "attach_evaluator_metadata",
    "encode_frame",
    "evaluator_telemetry_fields",
    "receive_frame",
    "send_frame",
]
