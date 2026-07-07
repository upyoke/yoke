"""Active-env manifest drift text for CLI help and unknown commands."""

from __future__ import annotations

from typing import List, Optional


def render_manifest_drift() -> str:
    """Help footer naming active-env commands this CLI build predates."""
    try:
        from yoke_cli.manifest import (
            active_env_manifest,
            server_only_subcommands,
        )

        manifest = active_env_manifest()
        if not manifest:
            return ""
        lines = [
            "Active env manifest: "
            f"{len(manifest.get('subcommands') or [])} subcommands served.",
        ]
        extra = server_only_subcommands(manifest)
        if extra:
            lines.append(
                "Server-only subcommands (rerun the public installer to "
                "update this CLI):"
            )
            lines.extend(
                f"  {_manifest_cli_label(row)}"
                f" -> {row.get('function_id')}"
                for row in extra
            )
        return "\n".join(lines)
    except Exception:
        return ""


def manifest_unknown_hint(argv: List[str]) -> Optional[str]:
    try:
        from yoke_cli.manifest import (
            active_env_manifest,
            manifest_knows,
        )

        manifest = active_env_manifest()
        if not manifest:
            return None
        row = manifest_knows(manifest, argv)
        if row is None:
            return None
        usage = str(row.get("usage") or "")
        label = str(row.get("help_label") or "")
        label_text = f" [{label}]" if label else ""
        hint = (
            "The active env serves this "
            f"subcommand{label_text} ({row.get('function_id')}); "
            "this CLI build predates it - rerun the public installer."
        )
        return hint + (f"\nServer usage: {usage}" if usage else "")
    except Exception:
        return None


def _manifest_cli_label(row: dict) -> str:
    cli_form = f"yoke {' '.join(row.get('tokens') or [])}"
    label = str(row.get("help_label") or "")
    return f"{cli_form} [{label}]" if label else cli_form


__all__ = ["manifest_unknown_hint", "render_manifest_drift"]
