"""Client-owned wall clock for one ``yoke hook evaluate`` process."""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from yoke_cli.transport.bounded_json_http import request_json
from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES
from yoke_contracts.hook_evaluator_protocol import (
    HOOK_CLIENT_WALL_BATCH_FIELD,
    HOOK_CLIENT_WALL_PATH,
)


_IMPORT_MONOTONIC = time.monotonic()


def _linux_process_age() -> float | None:
    try:
        raw = Path("/proc/self/stat").read_text(encoding="utf-8")
        start_ticks = int(raw.rsplit(")", 1)[1].split()[19])
        ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
        boot_clock = getattr(time, "CLOCK_BOOTTIME", None)
        since_boot = (
            time.clock_gettime(boot_clock)
            if boot_clock is not None
            else float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        )
    except (IndexError, OSError, TypeError, ValueError):
        return None
    return max(0.0, since_boot - (start_ticks / ticks_per_second))


def _darwin_process_age() -> float | None:
    try:
        import ctypes

        class ProcBsdInfo(ctypes.Structure):
            _fields_ = [
                ("flags", ctypes.c_uint32),
                ("status", ctypes.c_uint32),
                ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32),
                ("ppid", ctypes.c_uint32),
                ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32),
                ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32),
                ("svgid", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16),
                ("name", ctypes.c_char * 32),
                ("nfiles", ctypes.c_uint32),
                ("pgid", ctypes.c_uint32),
                ("pjobc", ctypes.c_uint32),
                ("tdev", ctypes.c_uint32),
                ("tpgid", ctypes.c_uint32),
                ("nice", ctypes.c_int32),
                ("start_seconds", ctypes.c_uint64),
                ("start_microseconds", ctypes.c_uint64),
            ]

        info = ProcBsdInfo()
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        size = ctypes.sizeof(info)
        read = libproc.proc_pidinfo(os.getpid(), 3, 0, ctypes.byref(info), size)
        if read != size or not info.start_seconds:
            return None
        started = info.start_seconds + info.start_microseconds / 1_000_000
        return max(0.0, time.time() - started)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _process_age() -> float | None:
    if sys.platform.startswith("linux"):
        return _linux_process_age()
    if sys.platform == "darwin":
        return _darwin_process_age()
    return None


@dataclass(frozen=True)
class HookClientWall:
    """Stable telemetry identity plus the hook child's monotonic origin."""

    event_id: str
    started_monotonic: float

    @classmethod
    def start(cls) -> "HookClientWall":
        entry = time.monotonic()
        process_age = _process_age()
        started = entry - process_age if process_age is not None else _IMPORT_MONOTONIC
        return cls(event_id=str(uuid.uuid4()), started_monotonic=min(entry, started))

    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started_monotonic) * 1000))


def record_client_wall(event_id: str, client_wall_ms: int) -> None:
    """Complete local or HTTPS telemetry without changing hook outcome."""
    try:
        from yoke_cli.transport.https import resolve_https_connection

        connection = resolve_https_connection()
        if connection is None:
            module = importlib.import_module("yoke_core.domain.hook_client_wall")
            module.record_client_wall_reports([(event_id, client_wall_ms)])
            return
        body = {
            "hook_schema": 1,
            HOOK_CLIENT_WALL_BATCH_FIELD: [
                {"event_id": event_id, "client_wall_ms": client_wall_ms}
            ],
        }
        request = urllib.request.Request(
            connection.api_url.rstrip("/") + HOOK_CLIENT_WALL_PATH,
            data=json.dumps(body, separators=(",", ":")).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {connection.token}",
            },
        )
        request_json(
            request,
            timeout_seconds=2.0,
            replay_safe=False,
            allow_loopback_http=True,
            response_limit_bytes=SMALL_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(connection.token,),
        )
    except Exception:
        return


__all__ = ["HookClientWall", "record_client_wall"]
