"""Retire path-owned lane settings across the declared harness registry."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.harness_folder_trust import claude_state_path, cursor_projects_root
from yoke_contracts.harness_lane_config_edit import edit_codex, edit_cursor, edit_json
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.machine_config.runtime import read_settings
from yoke_contracts.machine_config.settings_keys import machine_setting_default

SWEEP_COMMAND = "yoke harness lane-config sweep"
RECOVERY = f"Repair the named config or permissions, then run `{SWEEP_COMMAND}`."


def managed_lane_roots(checkouts: tuple[Path, ...]) -> tuple[Path, ...]:
    configured = read_settings().get("worktrees_dir") or machine_setting_default(
        "worktrees_dir"
    )
    return tuple(
        root.resolve() / suffix
        for root in checkouts
        for suffix in dict.fromkeys((configured, ".worktrees", ".claude/worktrees"))
    )


def cleanup_lane_configs(
    *,
    checkout: Path | None = None,
    managed_roots: tuple[Path, ...] = (),
    dry_run: bool = False,
    keep_backup: bool = False,
) -> dict:
    """Drop exact retired-path settings, or missing paths inside managed roots.

    Retirement supplies one proved-disposable lane. A sweep supplies managed
    lane/deploy/fixture roots: paths outside them and all live paths remain.
    This ownership rule requires no ledger or other persistent record store.
    """
    rows = []
    exact = checkout.expanduser().resolve() if checkout is not None else None
    roots = tuple(root.expanduser().resolve() for root in managed_roots)

    def selected(owner: str) -> bool:
        candidate = Path(owner).expanduser()
        if not candidate.is_absolute():
            return False
        candidate = candidate.resolve()
        if exact is not None:
            return candidate == exact
        return (
            any(candidate.is_relative_to(root) for root in roots)
            and not candidate.exists()
        )

    for family, spec in HARNESS_MACHINE_HOOKS.items():
        # Read actual config files, even if a harness has since been removed.
        if spec.trust == "codex_trusted_hash":
            targets, editor = [codex_config_path()], edit_codex
        elif family == "claude-code":
            targets, editor = [claude_state_path()], edit_json
        else:
            projects = cursor_projects_root()
            targets, editor = sorted(projects.glob("*/.workspace-trusted")), edit_cursor
        for target in targets:
            if not target.is_file():
                continue
            try:
                result = editor(
                    target, selected, dry_run=dry_run, keep_backup=keep_backup
                )
                if result["removed"]:
                    rows.append(dict(harness=family, file=str(target), **result))
            except Exception as exc:
                rows.append(
                    dict(
                        harness=family,
                        file=str(target),
                        error="harness_lane_config_cleanup_failed",
                        detail=str(exc),
                        recovery=RECOVERY,
                    )
                )
    return dict(ok=not any("error" in row for row in rows), dry_run=dry_run, files=rows)


def worktree_cleanup_warning(worktree: str | Path) -> str:
    """Name failed cleanup and its recovery at every existing retirement caller."""
    receipt = cleanup_lane_configs(checkout=Path(worktree))
    failures = [row for row in receipt["files"] if "error" in row]
    if failures:
        return (
            f"harness_lane_config_cleanup_failed for {worktree}: {failures}. {RECOVERY}"
        )
    return ""
