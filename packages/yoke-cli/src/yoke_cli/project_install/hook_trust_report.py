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


def report_lines(install_report: Any) -> List[str]:
    """Read the approval sentences out of an install report."""
    if not isinstance(install_report, Mapping):
        return []
    return [str(line) for line in (install_report.get(REPORT_KEY) or [])]


__all__ = [
    "HARNESS_ID_BY_HOOKS_KEY",
    "REPORT_KEY",
    "report_lines",
    "teaching_for_hooks_key",
]
