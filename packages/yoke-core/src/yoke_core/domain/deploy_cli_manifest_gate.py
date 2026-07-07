"""Post-deploy CLI manifest parity gate for Yoke core envs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CliManifestGateResult:
    ok: bool
    checked: bool
    message: str


def verify_deployed_cli_manifest(env_name: str) -> CliManifestGateResult:
    """Verify a target HTTPS env serves this checkout's CLI manifest."""
    env_name = str(env_name or "").strip()
    if not env_name:
        return CliManifestGateResult(True, False, "cli-manifest gate skipped")
    if not _env_is_https(env_name):
        return CliManifestGateResult(
            True,
            False,
            f"cli-manifest gate skipped: env {env_name!r} is not HTTPS",
        )

    from yoke_cli.manifest import (
        build_manifest,
        diagnose_env_manifest_fetch,
        fetch_env_manifest,
    )

    remote = fetch_env_manifest(env_name)
    if remote is None:
        reason = diagnose_env_manifest_fetch(env_name)
        suffix = f" — {reason}" if reason else ""
        return CliManifestGateResult(
            False,
            True,
            f"cli-manifest gate failed: could not fetch env {env_name!r} "
            f"manifest after deploy{suffix}",
        )
    local = build_manifest()
    return _compare_manifests(env_name, local, remote)


def _env_is_https(env_name: str) -> bool:
    try:
        from yoke_core.domain import machine_config
        from yoke_contracts.machine_config.schema import TRANSPORT_HTTPS

        connection = machine_config.active_connection(explicit_env=env_name)
        return str(connection.get("transport") or "") == TRANSPORT_HTTPS
    except Exception:
        return False


def _compare_manifests(
    env_name: str,
    local: Mapping[str, Any],
    remote: Mapping[str, Any],
) -> CliManifestGateResult:
    local_rows = _function_rows(local)
    remote_rows = _function_rows(remote)
    missing = sorted(set(local_rows) - set(remote_rows))
    mismatched = sorted(
        fid for fid in set(local_rows) & set(remote_rows)
        if local_rows[fid] != remote_rows[fid]
    )
    if not missing and not mismatched:
        return CliManifestGateResult(
            True, True, f"cli-manifest gate passed for env {env_name!r}",
        )
    bits: list[str] = []
    if missing:
        bits.append(
            "missing "
            + ", ".join(_format_row(fid, local_rows[fid]) for fid in missing[:8])
        )
    if mismatched:
        bits.append(
            "token mismatch "
            + ", ".join(
                f"{fid}: local `yoke {' '.join(local_rows[fid])}`, "
                f"remote `yoke {' '.join(remote_rows[fid])}`"
                for fid in mismatched[:8]
            )
        )
    return CliManifestGateResult(
        False,
        True,
        f"cli-manifest gate failed for env {env_name!r}: {'; '.join(bits)}. "
        "Deploy/update the Yoke API before marking the release healthy.",
    )


def _function_rows(manifest: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    rows = manifest.get("subcommands")
    if not isinstance(rows, list):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        fid = str(row.get("function_id") or "")
        tokens = row.get("tokens")
        if fid and isinstance(tokens, list):
            out[fid] = tuple(str(token) for token in tokens)
    return out


def _format_row(function_id: str, tokens: tuple[str, ...]) -> str:
    return f"{function_id} (`yoke {' '.join(tokens)}`)"


__all__ = [
    "CliManifestGateResult",
    "verify_deployed_cli_manifest",
]
