"""Ask each installed surface which models it will accept, on the relay cadence.

The relay is the only component that runs vendor binaries, so it is where
availability is observed. Readings ride the heartbeat this machine already
sends, which is why a new model becomes visible to steering within one poll
rather than within one release of Yoke.

Every failure keeps the models the surface last published and says the
reading is stale. Withdrawing a model because a probe timed out would report
the one thing that is certainly untrue.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_contracts.session_control.native_model_parsers import (
    CODEX_LIST_SOURCE,
    CURSOR_LIST_SOURCE,
    codex_next_cursor,
    parse_codex_models,
    parse_cursor_models,
)
from yoke_contracts.session_control.native_models import (
    MAX_MODELS_PER_SURFACE,
    NATIVE_MODEL_SURFACES,
    NO_ADAPTER_REASON,
    empty_reading,
    models_reading,
    sanitize_native_models,
    stale_reading,
)
from yoke_harness.session_relay_codex_app_server_client import (
    CodexAppServerError,
    _Client,
)
from yoke_harness.session_relay_codex_app_server_reasons import (
    app_server_failure_reason,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_surface_probes import resolve_native_cli


#: Fast enough that a model published mid-session is selectable within the
#: minute, slow enough that a machine polling every few seconds is not
#: spawning an app-server on each one.
NATIVE_MODEL_REFRESH_SECONDS = 45
NATIVE_MODEL_CACHE_FILE_NAME = "native-models.json"
#: Bumped whenever the cached reading shape changes, so an upgraded relay
#: publishes real readings on its first poll rather than unreadable ones.
NATIVE_MODEL_CACHE_SCHEMA_VERSION = 1
NATIVE_MODEL_PROBE_TIMEOUT_SECONDS = 20.0
_CODEX_LIST_METHOD = "model/list"
_CODEX_OPERATION = "codex native model listing"
_CURSOR_OPERATION = "cursor native model listing"

_failures = FailureReporter()


def _bounded_output(completed: subprocess.CompletedProcess[str]) -> str:
    """One line of the child's own words, so a log entry stays a log entry."""
    text = (completed.stderr or completed.stdout or "").strip().splitlines()
    return text[0][:160] if text else "no output"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_path(state_dir: Path | None) -> Path:
    return (state_dir or relay_state_dir()) / NATIVE_MODEL_CACHE_FILE_NAME


def _read_cache(state_dir: Path | None) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "schema_version": NATIVE_MODEL_CACHE_SCHEMA_VERSION,
        "probed_at": 0.0,
        "surfaces": {},
    }
    try:
        payload = json.loads(_cache_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return empty
    if not isinstance(payload, Mapping):
        return empty
    if payload.get("schema_version") != NATIVE_MODEL_CACHE_SCHEMA_VERSION:
        return empty
    try:
        probed_at = float(payload.get("probed_at") or 0)
    except (TypeError, ValueError):
        probed_at = 0.0
    surfaces = payload.get("surfaces")
    return {
        "schema_version": NATIVE_MODEL_CACHE_SCHEMA_VERSION,
        "probed_at": probed_at,
        "surfaces": dict(surfaces) if isinstance(surfaces, Mapping) else {},
    }


def _write_cache(document: Mapping[str, Any], state_dir: Path | None) -> None:
    path = _cache_path(state_dir)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _cursor_failure(reason: str, detail: str) -> dict[str, Any]:
    """Name a Cursor listing failure in the reading and in the relay log.

    A probe that throws its diagnostics away cannot be debugged later, and a
    surface that is merely misconfigured then reads exactly like one that is
    broken.
    """
    _failures.failed(_CURSOR_OPERATION, detail)
    return empty_reading("cursor-cli", "unknown", reason, source=CURSOR_LIST_SOURCE)


def probe_cursor_cli_models(*, observed_at: str) -> dict[str, Any]:
    """List Cursor's own accepted models from the installed agent."""
    executable = resolve_native_cli(harness_cli_manifest("cursor").executable)
    if not executable:
        return _cursor_failure("cli_unavailable", "cursor-agent was not found")
    try:
        completed = subprocess.run(
            [executable, "--list-models"],
            capture_output=True,
            check=False,
            text=True,
            timeout=NATIVE_MODEL_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _cursor_failure(
            "list_models_timeout",
            f"--list-models exceeded {NATIVE_MODEL_PROBE_TIMEOUT_SECONDS:g}s",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _cursor_failure(
            f"list_models_raised_{type(exc).__name__}", f"{type(exc).__name__}: {exc}"
        )
    if completed.returncode != 0:
        return _cursor_failure(
            f"list_models_exit_{completed.returncode}", _bounded_output(completed)
        )
    models = parse_cursor_models(completed.stdout)
    if not models:
        return _cursor_failure(
            "list_models_returned_no_model_rows", _bounded_output(completed)
        )
    _failures.recovered(_CURSOR_OPERATION)
    return models_reading(
        "cursor-cli", models, source=CURSOR_LIST_SOURCE, observed_at=observed_at
    )


def probe_codex_cli_models(*, observed_at: str) -> dict[str, Any]:
    """List Codex's accepted models over the app-server the relay already uses."""
    client: _Client | None = None
    models: list[dict[str, Any]] = []
    try:
        client = _Client(
            "codex",
            Path.home(),
            native_session_environment(executor="codex", provider="openai"),
            NATIVE_MODEL_PROBE_TIMEOUT_SECONDS,
            capture_stderr=True,
        )
        cursor: str | None = None
        while len(models) < MAX_MODELS_PER_SURFACE:
            page = client.request(
                _CODEX_LIST_METHOD, {"cursor": cursor} if cursor else {}
            )
            models.extend(parse_codex_models(page))
            cursor = codex_next_cursor(page)
            if not cursor:
                break
    except CodexAppServerError as failure:
        reason = app_server_failure_reason(failure)
        tail = client.stderr_tail() if client is not None else ""
        _failures.failed(
            _CODEX_OPERATION,
            f"{reason} ({failure}); child stderr: {tail or '<empty>'}",
        )
        return empty_reading("codex-cli", "unknown", reason, source=CODEX_LIST_SOURCE)
    finally:
        if client is not None:
            client.close()
    if not models:
        return empty_reading(
            "codex-cli",
            "unknown",
            "model_list_returned_no_models",
            source=CODEX_LIST_SOURCE,
        )
    _failures.recovered(_CODEX_OPERATION)
    return models_reading(
        "codex-cli",
        models[:MAX_MODELS_PER_SURFACE],
        source=CODEX_LIST_SOURCE,
        observed_at=observed_at,
    )


#: Only a surface Yoke has an adapter for is probed. Every other surface —
#: each desktop app, each editor extension, and any CLI whose listing route
#: is not yet written — reports that absence by name, because shipping one
#: vendor's CLI adapter proves nothing about the same vendor's desktop app.
NATIVE_MODEL_PROBES: dict[str, Callable[..., dict[str, Any]]] = {
    "codex-cli": probe_codex_cli_models,
    "cursor-cli": probe_cursor_cli_models,
}


def _probe_one(surface: str, observed_at: str) -> dict[str, Any]:
    probe = NATIVE_MODEL_PROBES.get(surface)
    if probe is None:
        return empty_reading(surface, "unsupported", NO_ADAPTER_REASON)
    try:
        return probe(observed_at=observed_at)
    except Exception as exc:
        # Collapsing every exception into one reason is how a surface that
        # is merely misconfigured reads the same as one that is broken.
        _failures.failed(
            f"{surface} native model listing", f"{type(exc).__name__}: {exc}"
        )
        return empty_reading(surface, "unknown", f"probe_raised_{type(exc).__name__}")


def _merge(
    surface: str,
    fresh: dict[str, Any],
    cached: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the last published models when a fresh attempt found none."""
    if fresh.get("status") == "ok" or fresh.get("status") == "unsupported":
        return fresh
    previous = cached.get(surface)
    reason = str(fresh.get("reason") or "probe_failed")
    return stale_reading(
        previous if isinstance(previous, Mapping) else None, surface, reason
    )


def observe_native_models(
    surfaces: Sequence[str] | None = None,
    *,
    state_dir: Path | None = None,
    now: float | None = None,
    clock: Callable[[], str] = _now_iso,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return cached readings, refreshing the installed surfaces on cadence.

    ``force`` skips the cadence for a bounded refresh at dispatch time, when a
    caller is about to place work and wants this machine's newest answer.
    """
    current = time.time() if now is None else now
    wanted = tuple(
        surface
        for surface in NATIVE_MODEL_SURFACES
        if surfaces is None or surface in set(surfaces)
    )
    document = _read_cache(state_dir)
    cached = sanitize_native_models(document.get("surfaces"))
    fresh_enough = (
        current - float(document.get("probed_at") or 0)
    ) < NATIVE_MODEL_REFRESH_SECONDS
    if not force and fresh_enough and all(surface in cached for surface in wanted):
        return {surface: cached[surface] for surface in wanted}
    observed_at = clock()
    probeable = tuple(surface for surface in wanted if surface in NATIVE_MODEL_PROBES)
    readings: dict[str, dict[str, Any]] = {
        surface: empty_reading(surface, "unsupported", NO_ADAPTER_REASON)
        for surface in wanted
        if surface not in NATIVE_MODEL_PROBES
    }
    if probeable:
        with ThreadPoolExecutor(max_workers=len(probeable)) as pool:
            futures = {
                pool.submit(_probe_one, surface, observed_at): surface
                for surface in probeable
            }
            for future, surface in futures.items():
                readings[surface] = _merge(surface, future.result(), cached)
    merged = dict(cached)
    merged.update(readings)
    kept = {surface: merged[surface] for surface in wanted if surface in merged}
    _write_cache(
        {
            "schema_version": NATIVE_MODEL_CACHE_SCHEMA_VERSION,
            "probed_at": current,
            "surfaces": kept,
        },
        state_dir,
    )
    return sanitize_native_models(kept)


__all__ = [
    "NATIVE_MODEL_CACHE_FILE_NAME",
    "NATIVE_MODEL_CACHE_SCHEMA_VERSION",
    "NATIVE_MODEL_PROBES",
    "NATIVE_MODEL_PROBE_TIMEOUT_SECONDS",
    "NATIVE_MODEL_REFRESH_SECONDS",
    "observe_native_models",
    "probe_codex_cli_models",
    "probe_cursor_cli_models",
]
