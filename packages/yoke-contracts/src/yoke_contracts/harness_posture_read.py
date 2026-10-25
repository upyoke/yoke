"""Read the actual unattended modes for each installed harness surface."""

from pathlib import Path
from typing import Optional, Tuple

from yoke_contracts.harness_unattended_posture import (
    CLAUDE_FAMILY,
    POSTURE_ABSENT,
    POSTURE_PROMPTS,
    POSTURE_UNATTENDED,
    claude_config_path,
    claude_settings_path,
    claude_settings_problems,
    managed_config_paths,
    posture_problems,
    read_posture_config,
)


def posture_findings(
    harness_id: str, surface_id: Optional[str] = None
) -> Optional[Tuple[str, ...]]:
    """One harness's verdict, or ``None`` when it is not set up here.

    Claude's modes depend on the surface: ``claude-cli`` reads its settings
    file, ``claude-desktop`` its app preference, and an unnamed surface both
    (the preference only once the desktop has created its config). Each surface requires its own unattended mode.
    """
    if harness_id == CLAUDE_FAMILY:
        desktop_path, settings_path = claude_config_path(), claude_settings_path()
        if not (settings_path.parent.is_dir() or desktop_path.exists()):
            return None
        desktop, _reason = read_posture_config(harness_id, desktop_path)
        settings, reason = read_posture_config(harness_id, settings_path)
        if settings is None and settings_path.exists():
            return (f"{settings_path}: {reason}",)
        app = _sourced(desktop_path, posture_problems(harness_id, desktop or {}))
        cli = _sourced(settings_path, claude_settings_problems(settings or {}))
        mode = {"claude-cli": cli, "claude-desktop": app}.get(
            surface_id or "", (app if desktop_path.exists() else ()) + cli
        )
    else:
        config, _reason = read_posture_config(harness_id)
        if config is None:
            return None
        mode = _sourced(
            managed_config_paths()[harness_id], posture_problems(harness_id, config)
        )
    return mode


def _sourced(source: Path, problems: Tuple[str, ...]) -> Tuple[str, ...]:
    """Prefix each problem with the file it was read from."""
    return tuple(f"{source}: {problem}" for problem in problems)


def posture_state(harness_id: str) -> str:
    """Report whether ``yoke`` runs unprompted on one harness, as one word."""
    findings = posture_findings(harness_id)
    if findings is None:
        return POSTURE_ABSENT
    return POSTURE_PROMPTS if findings else POSTURE_UNATTENDED
