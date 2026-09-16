"""Review body assembly mixin for the onboarding wizard flow."""

from __future__ import annotations

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify


class FinishBodyFlow:
    """Build the review screen from the shell's prepared model."""

    def _build_finish(self) -> list:
        return steps.finish_body(
            self._review_plan,
            problems=getattr(self, "_review_problems", []),
            notes=getattr(self, "_review_notes", []),
            machine_github_saved=self.result.machine_github_saved,
            show_all=getattr(self, "_review_show_all", False),
            status_lines=self._review_status_lines(),
        )

    def _review_status_lines(self) -> list[str]:
        lines: list[str] = []
        verification = self.result.yoke_token_verification
        if isinstance(verification, dict):
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


__all__ = ["FinishBodyFlow"]
