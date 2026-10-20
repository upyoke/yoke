"""Prepare default project art and persist it after setup Apply."""

from __future__ import annotations

import secrets
from typing import Any

from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_board_art_publication as art_publication
from yoke_cli.config import onboard_wizard_board_art_apply as art_apply
from yoke_cli.config.onboard_wizard import WizardApplyError
from yoke_cli.config.setup_run_facts import BOARD_ART_SEED
from yoke_contracts.project_contract.board_art import (
    generate_default_variants,
    resolve_project_art_word,
)


class BoardArtFlow:
    def _prepare_board_art_and_continue(self) -> None:
        if not self.result.board_art_word:
            self.result.board_art_word = resolve_project_art_word(
                self.result.project_name or "",
                slug=self.result.project_slug,
                short_code=self.result.project_public_item_prefix,
            )
        if not self.result.board_art_seed:
            # One seed per run: a replayed Project step shows the same art
            # Review showed, and Apply writes that art.
            seed = self._run_facts.get(BOARD_ART_SEED) or secrets.token_hex(16)
            self._run_facts.record(BOARD_ART_SEED, seed)
            self.result.board_art_seed = seed
        if not self.result.board_art_variants:
            self.result.board_art_variants = generate_default_variants(
                self.result.board_art_word, seed_text=self.result.board_art_seed
            )
        self._goto_hosting()

    def _board_art_after_apply(self, report: Any) -> bool:
        """Write, rebuild, commit, and publish the art; report whether it landed.

        Returns True when the art was committed, so the Apply summary can say
        so on the one screen that reports everything this run did. No saved
        variants, or no resolvable checkout, means there is nothing to do. The
        commit is what keeps a freshly installed checkout from being dirty
        with the installer's own output; publishing it beside setup's commit
        is what puts the art on the remote.
        """
        if not self.result.board_art_variants:
            return False
        repo_root = art_apply.repo_root_from_report(
            report, self.result.project_checkout
        )
        if repo_root is None:
            return False
        fallback_path = getattr(self, "report_path", None)
        try:
            art_apply.write_board_art(
                repo_root,
                self.result.board_art_word or "",
                self.result.board_art_variants,
            )
            art_apply.rebuild_board(repo_root)
            receipt = art_apply.commit_board_art(repo_root, report)
            art_apply.record_board_art_done(report, receipt, report_path=fallback_path)
            art_publication.publish_board_art(
                repo_root, report, receipt, report_path=fallback_path
            )
        except Exception as exc:  # noqa: BLE001 - route through Apply recovery
            summary = art_apply.mark_board_art_failed(
                report,
                exc,
                report_path=fallback_path,
                resume_command=getattr(self, "resume_command", None),
            )
            raise WizardApplyError(
                f"couldn't finish your board art: {exc}",
                failed_step=(
                    summary.get("failed_step") or art_apply.BOARD_ART_STEP_ACTION
                ),
                report_path=(summary.get("path") or fallback_path),
                resume_command=(
                    summary.get("resume_command")
                    or getattr(self, "resume_command", None)
                    or onboard_apply_report.RESUME_COMMAND
                ),
            ) from exc
        return True


__all__ = ["BoardArtFlow"]
