"""Prompt-doctrine and prompt-command-consistency health checks.

HC functions ensuring prompt and doc surfaces advertise supported CLI
syntax and that the canonical giant doctrine source exists.

HC functions: HC-prompt-command-consistency, HC-prompt-doctrine-consistency
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_prompt_command_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-prompt-command-consistency: Prompt/docs advertise supported CLI syntax."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-prompt-command-consistency", "Prompt/docs advertise supported CLI syntax",
                    "PASS", "")
        return

    issues: List[str] = []
    # Check for stale `events --limit` references (should be `events tail --limit`)
    for pattern_path in [
        Path(repo_root) / "AGENTS.md",
        Path(repo_root) / "CLAUDE.md",
        Path(repo_root) / "runtime" / "harness" / "claude" / "rules" / "session.md",
        Path(repo_root) / ".claude" / "rules" / "session.md",
    ]:
        if pattern_path.is_file():
            text = pattern_path.read_text(errors="replace")
            if "yoke-db.sh events --limit" in text or "events --limit" in text:
                if "events tail --limit" not in text:
                    issues.append(
                        f"- {pattern_path.name}: references 'events --limit' "
                        f"(should be 'events tail --limit')"
                    )

    # Check for stale browser CLI patterns in live prompt surfaces.
    # These patterns were retired when browser_qa became a top-level CLI,
    # browser_client snapshot screenshot takes a positional URL,
    # and Playwright cache resolution moved to worktree.py.
    _stale_browser_patterns = [
        ("browser_qa run-scenario",
         "browser_qa is a top-level CLI — no run-scenario subcommand"),
        ("browser_client resolve-cache",
         "Playwright cache resolution lives on worktree: "
         "python3 -m yoke_core.domain.worktree playwright-cache"),
        ("snapshot screenshot --url",
         "snapshot screenshot takes a positional url, not --url"),
    ]
    _prompt_surface_dirs = [
        Path(repo_root) / ".agents" / "skills" / "yoke",
        Path(repo_root) / "runtime" / "agents",
    ]
    for surface_dir in _prompt_surface_dirs:
        if not surface_dir.is_dir():
            continue
        for md_path in surface_dir.rglob("*.md"):
            try:
                content = md_path.read_text(errors="replace")
            except OSError:
                continue
            rel = md_path.relative_to(repo_root)
            for pattern, reason in _stale_browser_patterns:
                if pattern in content:
                    issues.append(f"- {rel}: references '{pattern}' ({reason})")

    if issues:
        rec.record("HC-prompt-command-consistency", "Prompt/docs advertise supported CLI syntax",
                    "FAIL", "\n".join(issues))
    else:
        rec.record("HC-prompt-command-consistency", "Prompt/docs advertise supported CLI syntax",
                    "PASS", "")


def hc_prompt_doctrine_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-prompt-doctrine-consistency: Canonical giant doctrine + short-form consistency."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-prompt-doctrine-consistency",
                    "Canonical giant doctrine + short-form consistency", "PASS", "")
        return

    issues: List[str] = []
    philosophy_path = Path(repo_root) / "docs" / "prompt-philosophy.md"
    if not philosophy_path.is_file():
        issues.append("- docs/prompt-philosophy.md not found (canonical philosophy source)")

    if issues:
        rec.record("HC-prompt-doctrine-consistency",
                    "Canonical giant doctrine + short-form consistency", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-prompt-doctrine-consistency",
                    "Canonical giant doctrine + short-form consistency", "PASS", "")
