"""Relay-side plan-limit probes. Credentials stay on this machine; values only leave."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_harness.session_relay_probe_cache import read_probe_cache, write_probe_cache
from yoke_contracts.timestamps import iso8601_now as _now_iso
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence

from yoke_contracts.session_control.plan_limit_parsers import (
    parse_claude_usage,
    parse_cursor_usage,
)
from yoke_contracts.session_control.plan_limits import (
    CLI_PLAN_LIMIT_SURFACES,
    PLAN_LIMIT_REFRESH_SECONDS,
    sanitize_plan_limits,
    unknown_reading,
)
from yoke_harness.session_relay_codex_plan_limit import probe_codex_cli
from yoke_harness.session_relay_environment import strip_relay_owned_python_state
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_plan_limit_http import (
    PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
    plan_limit_http_json,
)
from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_surface_probes import resolve_native_cli


PLAN_LIMIT_CACHE_FILE_NAME = "plan-limits.json"
# Bumped whenever the cached reading shape changes. A cache written by a
# different shape is discarded rather than reported, so an upgraded relay
# publishes real windows on its first poll instead of unreadable ones for
# the rest of the refresh interval.
PLAN_LIMIT_CACHE_SCHEMA_VERSION = 4
_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_CURSOR_RPC = "https://api2.cursor.sh/aiserver.v1.DashboardService/"

_failures = FailureReporter()


def _cache_path(state_dir: Path | None) -> Path:
    return (state_dir or relay_state_dir()) / PLAN_LIMIT_CACHE_FILE_NAME


def _read_cache(state_dir: Path | None) -> dict[str, Any]:
    return read_probe_cache(_cache_path(state_dir), PLAN_LIMIT_CACHE_SCHEMA_VERSION)


def _write_cache(document: Mapping[str, Any], state_dir: Path | None) -> None:
    write_probe_cache(_cache_path(state_dir), document)


def _keychain_password(service: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    secret = (completed.stdout or "").strip()
    return secret or None


def _load_claude_credentials() -> dict[str, Any] | str:
    raw = _keychain_password("Claude Code-credentials")
    if raw is None:
        path = Path.home() / ".claude" / ".credentials.json"
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return "stale_credential"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "stale_credential"
    return payload if isinstance(payload, dict) else "stale_credential"


def probe_claude_cli(*, observed_at: str) -> dict[str, Any]:
    credentials = _load_claude_credentials()
    if isinstance(credentials, str):
        return unknown_reading("claude-cli", credentials, observed_at=observed_at)
    oauth = credentials.get("claudeAiOauth")
    token = oauth.get("accessToken") if isinstance(oauth, Mapping) else None
    if not isinstance(token, str) or not token:
        return unknown_reading(
            "claude-cli", "stale_credential", observed_at=observed_at
        )
    usage = plan_limit_http_json(
        _CLAUDE_USAGE_URL, headers={"Authorization": f"Bearer {token}"}
    )
    if isinstance(usage, str):
        return unknown_reading("claude-cli", usage, observed_at=observed_at)
    return parse_claude_usage(credentials, usage, observed_at=observed_at)


def _cursor_access_token() -> str | None:
    if sys.platform == "darwin":
        return _keychain_password("cursor-access-token")
    if sys.platform != "linux":
        return None
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        credentials = json.loads(
            (root / "cursor" / "auth.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    token = credentials.get("accessToken") if isinstance(credentials, dict) else None
    return token if isinstance(token, str) and token.strip() else None


def probe_cursor_cli(*, observed_at: str) -> dict[str, Any]:
    token = _cursor_access_token()
    if not token:
        return unknown_reading(
            "cursor-cli", "stale_credential", observed_at=observed_at
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
    }
    plan = plan_limit_http_json(
        _CURSOR_RPC + "GetPlanInfo", headers=headers, data=b"{}", method="POST"
    )
    usage = plan_limit_http_json(
        _CURSOR_RPC + "GetCurrentPeriodUsage",
        headers=headers,
        data=b"{}",
        method="POST",
    )
    if isinstance(usage, str):
        return unknown_reading("cursor-cli", usage, observed_at=observed_at)
    plan_doc = plan if isinstance(plan, dict) else {}
    if not plan_doc:
        plan_doc = _cursor_tier_from_cli()
    return parse_cursor_usage(plan_doc, usage, observed_at=observed_at)


def _cursor_tier_from_cli() -> dict[str, Any]:
    binary = resolve_native_cli("cursor-agent")
    if not binary:
        return {}
    try:
        about = subprocess.run(
            [binary, "about", "--format", "json"],
            env=strip_relay_owned_python_state(),
            capture_output=True,
            text=True,
            timeout=PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        parsed = json.loads(about.stdout or "")
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}
    if isinstance(parsed, dict) and parsed.get("subscriptionTier"):
        return {"planName": parsed["subscriptionTier"]}
    return {}


_PROBES: dict[str, Callable[..., dict[str, Any]]] = {
    "claude-cli": probe_claude_cli,
    "codex-cli": probe_codex_cli,
    "cursor-cli": probe_cursor_cli,
}


def _probe_one(surface: str, observed_at: str) -> dict[str, Any]:
    probe = _PROBES.get(surface)
    if probe is None:
        return unknown_reading(surface, "unsupported_surface", observed_at=observed_at)
    try:
        return probe(observed_at=observed_at)
    except Exception as exc:
        # Collapsing every exception into one reason is how a surface that
        # is merely misconfigured reads the same as one that is broken.
        _failures.failed(f"{surface} plan-limit probe", f"{type(exc).__name__}: {exc}")
        return unknown_reading(
            surface, f"probe_raised_{type(exc).__name__}", observed_at=observed_at
        )


def observe_plan_limits(
    surfaces: Sequence[str],
    *,
    state_dir: Path | None = None,
    now: datetime | str | None = None,
    clock: Callable[[], str] = _now_iso,
) -> dict[str, dict[str, Any]]:
    """Return cached readings, refreshing connected CLI surfaces every 4 minutes."""
    current = utc_now() if now is None else parse_instant(now)
    wanted = tuple(
        surface for surface in CLI_PLAN_LIMIT_SURFACES if surface in set(surfaces)
    )
    document = _read_cache(state_dir)
    cached = sanitize_plan_limits(document.get("surfaces"))
    probed_at = document["probed_at"]
    fresh = probed_at is not None and (
        0 <= (current - probed_at).total_seconds() < PLAN_LIMIT_REFRESH_SECONDS
    )
    if fresh and all(surface in cached for surface in wanted):
        return {surface: cached[surface] for surface in wanted}
    observed_at = format_instant(clock())
    readings: dict[str, dict[str, Any]] = {}
    if wanted:
        with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
            futures = {
                pool.submit(_probe_one, surface, observed_at): surface
                for surface in wanted
            }
            for future, surface in futures.items():
                readings[surface] = future.result()
    merged = dict(cached)
    merged.update(readings)
    kept = {surface: merged[surface] for surface in wanted if surface in merged}
    _write_cache(
        {
            "schema_version": PLAN_LIMIT_CACHE_SCHEMA_VERSION,
            "probed_at": current,
            "surfaces": kept,
        },
        state_dir,
    )
    return sanitize_plan_limits(kept)


__all__ = [
    "PLAN_LIMIT_CACHE_FILE_NAME",
    "PLAN_LIMIT_CACHE_SCHEMA_VERSION",
    "PLAN_LIMIT_REFRESH_SECONDS",
    "observe_plan_limits",
]
