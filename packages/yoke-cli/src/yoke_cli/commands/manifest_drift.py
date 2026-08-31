"""Active-env manifest drift text for CLI help and unknown commands."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import List, Optional


def render_manifest_drift(*, explicit_env: str | None = None) -> str:
    """Help footer naming commands exposed only by the active env."""
    try:
        from yoke_cli.manifest import (
            active_env_manifest,
            server_only_subcommands,
        )

        manifest = active_env_manifest(explicit_env=explicit_env)
        if not manifest:
            return ""
        lines = [
            "Active env manifest: "
            f"{len(manifest.get('subcommands') or [])} subcommands served.",
        ]
        extra = server_only_subcommands(manifest)
        if extra:
            lines.append(
                "Active-env-only subcommands (availability alone does not "
                "identify which operating layer differs):"
            )
            for row in extra:
                lines.append(
                    f"  {_manifest_cli_label(row)} -> {row.get('function_id')}"
                )
                usage = str(row.get("usage") or "")
                if usage:
                    lines.append(f"    Server usage: {usage}")
        return "\n".join(lines)
    except Exception:
        return ""


def manifest_unknown_hint(
    argv: List[str],
    *,
    explicit_env: str | None = None,
) -> Optional[str]:
    try:
        from yoke_cli.operating_layer_drift import (
            installed_layer_recovery,
            running_identity,
        )

        running_version, running_module_file = running_identity()
        layer_recovery = installed_layer_recovery(Path.cwd())
    except Exception:
        running_version, running_module_file, layer_recovery = "", "", ""
    try:
        from yoke_cli.manifest import (
            active_env_manifest,
            manifest_knows,
        )

        manifest = active_env_manifest(
            explicit_env=explicit_env,
            force_refresh=True,
        )
        if not manifest:
            return layer_recovery or None
        row = manifest_knows(manifest, argv)
        if row is None:
            return layer_recovery or None
        usage = str(row.get("usage") or "")
        label = str(row.get("help_label") or "")
        label_text = f" [{label}]" if label else ""
        hint = (
            "The active env serves this "
            f"subcommand{label_text} ({row.get('function_id')}); "
            "it is not available in the running local command registry."
        )
        recovery = layer_recovery or _server_recovery(
            manifest,
            running_version=running_version,
            running_module_file=running_module_file,
        )
        if recovery:
            hint = f"{hint}\n{recovery}"
        return hint + (f"\nServer usage: {usage}" if usage else "")
    except Exception:
        return layer_recovery or None


def _server_recovery(
    manifest: dict,
    *,
    running_version: str,
    running_module_file: str,
) -> str:
    """Diagnose client/server skew only from fresh release evidence.

    Project teaching is checked before client/server release skew because an
    older installed layer can hide a command even while the running CLI and
    active server are both current.  Only a directional comparison recommends
    changing one side.
    """
    from yoke_cli.operating_layer_drift import (
        RUNNING_AHEAD,
        RUNNING_BEHIND,
        RUNNING_DIVERGED,
        RUNNING_EQUAL,
        compare_running_to_release,
    )

    server_version = str(manifest.get("server_engine_version") or "")
    running = compare_running_to_release(
        server_version,
        running_version=running_version,
        running_module_file=running_module_file,
    )
    if running.relationship == RUNNING_BEHIND:
        if running.source_checkout:
            command = (
                "git -C "
                f"{shlex.quote(running.source_checkout)} pull --ff-only"
            )
            return (
                "The running source checkout is behind the active server "
                f"release. Update that checkout with `{command}`, then retry. "
                "The public installer does not update a source checkout."
            )
        return (
            "The running CLI/source checkout is behind the active server "
            "release. Rerun the public installer to update this CLI, then "
            "retry."
        )
    if running.relationship == RUNNING_AHEAD:
        return (
            "The running CLI/source checkout is ahead of the active server "
            "release. Deploy the matching server release or wait for that "
            "deploy to finish, then retry. Do not reinstall the CLI; it is "
            "not the older side."
        )

    if running.relationship == RUNNING_EQUAL:
        diagnosis = (
            "The running CLI/source checkout and active server release "
            "compare equal, so version skew does not explain the missing "
            "command."
        )
    elif running.relationship == RUNNING_DIVERGED:
        diagnosis = (
            "The running source checkout and active server release have "
            "diverged, so neither side is established as older."
        )
    else:
        diagnosis = (
            "The available version/source evidence does not establish which "
            "operating layer is out of date."
        )
    return (
        f"{diagnosis} Verify the active env deployment and project "
        "operating-layer receipt before changing either side. Do not "
        "reinstall the CLI based on this unknown subcommand alone."
    )


def _manifest_cli_label(row: dict) -> str:
    cli_form = f"yoke {' '.join(row.get('tokens') or [])}"
    label = str(row.get("help_label") or "")
    return f"{cli_form} [{label}]" if label else cli_form


__all__ = ["manifest_unknown_hint", "render_manifest_drift"]
