"""CLI command/help manifest — server render + client fetch/cache.

The active env serves ``GET /v1/cli/manifest`` (auth-gated) rendering
its subcommand grammar from the same registries that drive ``yoke
--help`` locally. The machine client caches one manifest per env label
under the machine cache dir and uses it to surface drift: subcommands
the server knows that this CLI build predates point the operator at
`rerun the public installer` instead of a bare unknown-subcommand error
for help/capability compatibility. Local-postgres
transport never consults a manifest — the in-checkout registry is the
authority there.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_contracts.api_urls import join_api_url

MANIFEST_VERSION = 1
MANIFEST_PATH = "/v1/cli/manifest"
CACHE_SUBDIR = "cli-manifest"
CACHE_TTL_S = 24 * 3600
_FETCH_TIMEOUT_S = 5.0


def build_manifest() -> Dict[str, Any]:
    """Render the manifest from the live CLI registries (server side)."""
    from yoke_cli.commands.flag_adapters import ADAPTER_USAGE
    from yoke_cli.commands.help_labels import label_for_cli_form
    from yoke_cli.commands.registry import (
        SUBCOMMAND_ALIAS_REGISTRY,
        SUBCOMMAND_REGISTRY,
    )

    def _rows(registry) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for tokens, (function_id, _adapter) in sorted(registry.items()):
            cli_form = "yoke " + " ".join(tokens)
            row = {
                "tokens": list(tokens),
                "function_id": function_id,
                "usage": ADAPTER_USAGE.get(function_id, ""),
            }
            label = label_for_cli_form(cli_form)
            if label:
                row["help_label"] = label
            rows.append(row)
        return rows

    return {
        "manifest_version": MANIFEST_VERSION,
        "subcommands": _rows(SUBCOMMAND_REGISTRY),
        "aliases": _rows(SUBCOMMAND_ALIAS_REGISTRY),
    }


def active_env_manifest(*, allow_fetch: bool = True) -> Optional[Dict[str, Any]]:
    """Return the active https env's manifest, or ``None``.

    ``None`` means "no manifest applies": local transport, no active
    connection, or fetch/cache both unavailable. Callers fall back to
    the local registry silently — manifest absence must never break a
    command.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        connection = resolve_https_connection()
    except Exception:
        return None
    if connection is None:
        return None
    from yoke_cli.config.machine_config import active_env

    try:
        env_name = active_env()
    except Exception:
        return None
    cache_path = _cache_path(env_name)
    cached = _read_cache(cache_path)
    if cached is not None and not _stale(cache_path):
        return cached
    if allow_fetch:
        fetched = _fetch(connection)
        if fetched is not None:
            _write_cache(cache_path, fetched)
            return fetched
    return cached


def fetch_env_manifest(env_name: str) -> Optional[Dict[str, Any]]:
    """Fetch one HTTPS env's manifest fresh, bypassing the cache."""
    try:
        from yoke_cli.transport.https import resolve_https_connection

        connection = resolve_https_connection(explicit_env=env_name)
    except Exception:
        return None
    if connection is None:
        return None
    return _fetch(connection)


def server_only_subcommands(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Manifest rows whose tokens this CLI build does not resolve."""
    from yoke_cli.commands.registry import (
        SUBCOMMAND_ALIAS_REGISTRY,
        SUBCOMMAND_REGISTRY,
    )

    local = {tuple(tokens) for tokens in SUBCOMMAND_REGISTRY}
    local.update(tuple(tokens) for tokens in SUBCOMMAND_ALIAS_REGISTRY)
    rows = list(manifest.get("subcommands") or [])
    rows.extend(manifest.get("aliases") or [])
    return [row for row in rows
            if tuple(row.get("tokens") or ()) not in local]


def manifest_knows(manifest: Dict[str, Any], argv: List[str]) -> Optional[Dict[str, Any]]:
    """Return the manifest row matching ``argv``'s leading tokens, if any."""
    rows = list(manifest.get("subcommands") or [])
    rows.extend(manifest.get("aliases") or [])
    by_tokens = {tuple(row.get("tokens") or ()): row for row in rows}
    for length in (3, 2, 1):
        candidate = tuple(argv[:length])
        if len(candidate) == length and candidate in by_tokens:
            return by_tokens[candidate]
    return None


def _cache_path(env_name: str) -> Path:
    from yoke_cli.config.machine_config import cache_dir

    return cache_dir() / CACHE_SUBDIR / f"{env_name}.json"


def _read_cache(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _stale(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) > CACHE_TTL_S
    except OSError:
        return True


def _write_cache(path: Path, manifest: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    except OSError:
        return


def _manifest_request(connection) -> urllib.request.Request:
    """Build the authenticated manifest GET for *connection*."""
    url = join_api_url(connection.api_url, MANIFEST_PATH)
    return urllib.request.Request(
        url, headers={"Authorization": f"Bearer {connection.token}"},
    )


def _fetch(connection) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(
            _manifest_request(connection), timeout=_FETCH_TIMEOUT_S
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def diagnose_env_manifest_fetch(env_name: str) -> str:
    """Return a short human reason the manifest fetch failed, or '' if it would
    succeed. Diagnostic-only: re-probes the env so the deploy gate can name
    *why* the fetch returned None (a 401, a 404, a timeout) instead of a bare
    "could not fetch". Never raises.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        connection = resolve_https_connection(explicit_env=env_name)
    except Exception as exc:
        return f"connection resolution failed: {exc}"
    if connection is None:
        return f"no HTTPS connection configured for env {env_name!r}"
    try:
        with urllib.request.urlopen(
            _manifest_request(connection), timeout=_FETCH_TIMEOUT_S
        ):
            return ""
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}{_http_error_detail(exc)}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"network error: {getattr(exc, 'reason', None) or exc}"


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Extract ``code ("message")`` from a Yoke JSON error body, if present."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return ""
    code = str(err.get("code") or "").strip()
    message = str(err.get("message") or "").strip()
    parts = [p for p in (code, f'("{message}")' if message else "") if p]
    return (" " + " ".join(parts)) if parts else ""


__all__ = [
    "CACHE_TTL_S",
    "MANIFEST_PATH",
    "MANIFEST_VERSION",
    "active_env_manifest",
    "build_manifest",
    "diagnose_env_manifest_fetch",
    "fetch_env_manifest",
    "manifest_knows",
    "server_only_subcommands",
]
