"""The harness-approval teaching an install report carries.

Writing hook glue is only half of making it run: every harness with an
approval gate re-requires the operator's approval for the file that was just
written, and Codex re-requires it again on any later content change because
its trust is keyed to the hash. An install that stays silent about that step
leaves a project whose hooks look installed and never fire.

So a run records one sentence per harness whose glue it wrote or updated,
and the surfaces that report the run — the installer's own JSON and the
onboarding wizard — read them from here rather than each deciding when a
harness owes an approval step.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from yoke_contracts.harness_hook_approval import trust_teaching

#: Install-report key holding the approval sentences for this run.
REPORT_KEY = "harness_hook_trust"

#: Which harness owns each bundle hook subtree, so the teaching is selected
#: from that harness's declaration instead of guessed from a settings path.
HARNESS_ID_BY_HOOKS_KEY = {
    "claude_settings_hooks": "claude-code",
    "codex_hooks": "codex",
    "cursor_hooks": "cursor",
}


def teaching_for_hooks_key(hooks_key: str) -> Optional[str]:
    """The approval sentence this subtree's harness owes, or ``None``."""
    return trust_teaching(HARNESS_ID_BY_HOOKS_KEY[hooks_key])


def harness_ids_written(install_report: Any) -> List[str]:
    """Harness ids whose glue this install run wrote or created."""
    from yoke_cli.project_install.hooks import SETTINGS_FILE_BY_HOOKS_KEY

    if not isinstance(install_report, Mapping):
        return []
    rel_to_harness = {
        settings_rel: HARNESS_ID_BY_HOOKS_KEY[hooks_key]
        for hooks_key, settings_rel in SETTINGS_FILE_BY_HOOKS_KEY.items()
        if hooks_key in HARNESS_ID_BY_HOOKS_KEY
    }
    written: set[str] = set()
    hooks_added = install_report.get("hooks_added") or {}
    created = install_report.get("created_settings_files") or []
    for rel in list(hooks_added) + list(created):
        harness_id = rel_to_harness.get(str(rel))
        if harness_id:
            written.add(harness_id)
    return sorted(written)


def report_lines(install_report: Any) -> List[str]:
    """Read the approval sentences out of an install report."""
    if not isinstance(install_report, Mapping):
        return []
    return [str(line) for line in (install_report.get(REPORT_KEY) or [])]


__all__ = [
    "HARNESS_ID_BY_HOOKS_KEY",
    "REPORT_KEY",
    "harness_ids_written",
    "report_lines",
    "teaching_for_hooks_key",
]
