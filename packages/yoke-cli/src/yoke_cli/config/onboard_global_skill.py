"""Install the user-level ``yoke-global`` skill as onboarding applies.

Every setup runs this step, a machine-only setup included: the skill is what
a session opened outside every project uses to pick or add a project. It is a
named Review step because it writes into the user's harness folders. A refusal
is reported on the Apply summary with its recovery rather than failing the
apply, since the rest of the machine is set up either way.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.global_skill_install import ensure_global_skill
from yoke_contracts.harness_global_skill import GLOBAL_SKILL_NAME, SHARED_SKILLS_DIR
from yoke_cli.config import onboard_apply_progress

INSTALL_ACTION = "install-yoke-global-skill"
INSTALL_TARGET = f"~/{SHARED_SKILLS_DIR}/{GLOBAL_SKILL_NAME}"


def plan_steps() -> list[dict[str, str]]:
    return [{"action": INSTALL_ACTION, "target": INSTALL_TARGET}]


def apply(
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    """Install the skill, recording the outcome on the onboarding report."""
    onboard_apply_progress.emit(progress, INSTALL_ACTION, INSTALL_TARGET, "running")
    result = ensure_global_skill()
    onboard_apply_progress.emit(
        progress,
        INSTALL_ACTION,
        INSTALL_TARGET,
        "failed" if result.refused else "done",
    )
    report["global_skill"] = result.to_json()


def summary_lines(fragment: Any) -> tuple[str, ...]:
    """The Apply-summary lines a refusal owes the operator; empty otherwise."""
    if not isinstance(fragment, Mapping) or not fragment.get("recovery"):
        return ()
    return (
        f"The {GLOBAL_SKILL_NAME} skill was not installed: {fragment.get('reason')}",
        str(fragment.get("recovery")),
    )


__all__ = ["INSTALL_ACTION", "INSTALL_TARGET", "apply", "plan_steps", "summary_lines"]
