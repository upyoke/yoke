"""Review body assembly mixin for the onboarding wizard flow."""

from __future__ import annotations

from yoke_cli.config import onboard_wizard_steps as steps


class FinishBodyFlow:
    """Build the review screen from the shell's prepared model."""

    def _build_finish(self) -> list:
        return steps.finish_body(
            self._review_plan,
            problems=getattr(self, "_review_problems", []),
            notes=getattr(self, "_review_notes", []),
            machine_github_saved=self.result.machine_github_saved,
        )


__all__ = ["FinishBodyFlow"]
