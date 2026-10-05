"""Review body assembly mixin for the onboarding wizard flow."""

from __future__ import annotations

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_wizard_machine_finish import (
    machine_finish_lines,
    machine_finish_widgets,
)
from yoke_cli.config.onboard_wizard_plan_review import _PLAN_GROUPS, classify_plan


class FinishBodyFlow:
    """Build the review screen from the shell's prepared model."""

    def _build_finish(self) -> list:
        widgets = steps.finish_body(
            self._review_plan,
            problems=getattr(self, "_review_problems", []),
            notes=getattr(self, "_review_notes", []),
            machine_github_saved=self.result.machine_github_saved,
            show_all=getattr(self, "_review_show_all", False),
            status_lines=self._review_status_lines(),
        )
        grouped = classify_plan(self._review_plan)
        if not any(grouped.get(key) for _label, _css, key in _PLAN_GROUPS):
            widgets[-1:-1] = machine_finish_widgets(self.result)
        return widgets

    def _review_status_lines(self) -> list[str]:
        lines: list[str] = []
        verification = self.result.yoke_token_verification
        machine_lines = machine_finish_lines(self.result)
        if machine_lines:
            lines.extend(machine_lines)
        elif isinstance(verification, dict):
            details = yoke_token_verify.detail_lines(verification)
            actor = next(
                (line for line in details if line.startswith("Actor:")),
                "Actor: verified",
            )
            lines.append(
                f"Connection: {actor.removeprefix('Actor: ').strip()} · "
                f"{len(verification.get('orgs') or [])} organizations · "
                f"{len(verification.get('projects') or [])} projects"
            )
        aws = self.result.hosting_verification
        if isinstance(aws, dict) and aws.get("ok"):
            lines.append(
                f"AWS: account {aws.get('account')} · {aws.get('identity')} · aws-admin saved locally"
            )
        return lines

    def _build_apply_success(self) -> list:
        widgets = steps.apply_success_body_from_report(
            self.report_path,
            getattr(self, "_applied_report", None),
            board_art_committed=getattr(self, "_board_art_committed", False),
        )
        widgets[-1:-1] = machine_finish_widgets(self.result)
        return widgets


__all__ = ["FinishBodyFlow"]
