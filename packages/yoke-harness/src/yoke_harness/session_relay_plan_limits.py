"""Relay-side plan-limit probes. Credentials stay on this machine; values only leave."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request

from yoke_contracts.session_control.plan_limits import (
    CLI_PLAN_LIMIT_SURFACES,
    parse_claude_usage,
    parse_codex_rate_limits,
    parse_cursor_usage,
    sanitize_plan_limits,
    unknown_reading,
)
from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_surface_probes import resolve_native_cli


PLAN_LIMIT_REFRESH_SECONDS = 5 * 60
PLAN_LIMIT_PROBE_TIMEOUT_SECONDS = 8.0
PLAN_LIMIT_CACHE_FILE_NAME = "plan-limits.json"
_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_CURSOR_RPC = "https://api2.cursor.sh/aiserver.v1.DashboardService/"
_CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
_CODEX_USER_AGENT = "codex_cli_rs/yoke-plan-limit-probe"
_CODEX_CLIENT = {"name": "yoke-limit-probe", "title": "Yoke", "version": "1"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_path(state_dir: Path | None) -> Path:
    return (state_dir or relay_state_dir()) / PLAN_LIMIT_CACHE_FILE_NAME


def _read_cache(state_dir: Path | None) -> dict[str, Any]:
    empty: dict[str, Any] = {"schema_version": 1, "probed_at": 0.0, "surfaces": {}}
    try:
        payload = json.loads(_cache_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return empty
    if not isinstance(payload, dict):
        return empty
    surfaces = payload.get("surfaces")
    try:
        probed_at = float(payload.get("probed_at") or 0)
    except (TypeError, ValueError):
        probed_at = 0.0
    return {
        "schema_version": 1,
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


def _keychain_password(service: str) -> str | None:
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


def _http_json(
    url: str,
    *,
    headers: Mapping[str, str],
    data: bytes | None = None,
    method: str | None = None,
) -> dict[str, Any] | str:
    request = urllib.request.Request(
        url, data=data, headers=dict(headers), method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=PLAN_LIMIT_PROBE_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "stale_credential"
        return f"http_{exc.code}"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError):
        return "usage_unreadable"
    return payload if isinstance(payload, dict) else "usage_unreadable"


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
    usage = _http_json(_CLAUDE_USAGE_URL, headers={"Authorization": f"Bearer {token}"})
    if isinstance(usage, str):
        return unknown_reading("claude-cli", usage, observed_at=observed_at)
    return parse_claude_usage(credentials, usage, observed_at=observed_at)


def _codex_app_server() -> dict[str, Any] | str:
    binary = resolve_native_cli("codex")
    if not binary:
        return "cli_unavailable"
    try:
        process = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        return "cli_unavailable"
    if process.stdin is None or process.stdout is None:
        process.kill()
        return "cli_unavailable"

    def send(payload: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    try:
        send({"id": 0, "method": "initialize", "params": {"clientInfo": _CODEX_CLIENT}})
        send({"method": "initialized", "params": None})
        send({"id": 1, "method": "account/rateLimits/read", "params": None})
        deadline = time.time() + PLAN_LIMIT_PROBE_TIMEOUT_SECONDS
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != 1:
                continue
            if "error" in message:
                return "unsupported_on_this_build"
            result = message.get("result")
            return result if isinstance(result, dict) else "usage_unreadable"
        return "usage_unreadable"
    finally:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def _codex_http() -> dict[str, Any] | str:
    path = Path.home() / ".codex" / "auth.json"
    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "stale_credential"
    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    if not isinstance(tokens, Mapping):
        return "stale_credential"
    token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(token, str) or not isinstance(account_id, str):
        return "stale_credential"
    return _http_json(
        _CODEX_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account_id,
            "User-Agent": _CODEX_USER_AGENT,
        },
    )


def probe_codex_cli(*, observed_at: str) -> dict[str, Any]:
    payload = _codex_app_server()
    if payload in {"unsupported_on_this_build", "cli_unavailable"}:
        payload = _codex_http()
    if isinstance(payload, str):
        return unknown_reading("codex-cli", payload, observed_at=observed_at)
    return parse_codex_rate_limits(payload, observed_at=observed_at)


def probe_cursor_cli(*, observed_at: str) -> dict[str, Any]:
    token = _keychain_password("cursor-access-token")
    if not token:
        return unknown_reading(
            "cursor-cli", "stale_credential", observed_at=observed_at
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
    }
    plan = _http_json(
        _CURSOR_RPC + "GetPlanInfo", headers=headers, data=b"{}", method="POST"
    )
    usage = _http_json(
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
    except Exception:
        return unknown_reading(surface, "usage_unreadable", observed_at=observed_at)


def observe_plan_limits(
    surfaces: Sequence[str],
    *,
    state_dir: Path | None = None,
    now: float | None = None,
    clock: Callable[[], str] = _now_iso,
) -> dict[str, dict[str, Any]]:
    """Return cached readings, refreshing connected CLI surfaces every 5 minutes."""
    current = time.time() if now is None else now
    wanted = tuple(
        surface for surface in CLI_PLAN_LIMIT_SURFACES if surface in set(surfaces)
    )
    document = _read_cache(state_dir)
    cached = sanitize_plan_limits(document.get("surfaces"))
    fresh = (
        current - float(document.get("probed_at") or 0)
    ) < PLAN_LIMIT_REFRESH_SECONDS
    if fresh and all(surface in cached for surface in wanted):
        return {surface: cached[surface] for surface in wanted}
    observed_at = clock()
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
        {"schema_version": 1, "probed_at": current, "surfaces": kept},
        state_dir,
    )
    return sanitize_plan_limits(kept)


__all__ = [
    "PLAN_LIMIT_CACHE_FILE_NAME",
    "PLAN_LIMIT_PROBE_TIMEOUT_SECONDS",
    "PLAN_LIMIT_REFRESH_SECONDS",
    "observe_plan_limits",
]
