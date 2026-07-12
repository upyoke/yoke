"""Board-art navigation for the ``yoke onboard`` wizard.

The flow previews an editable progress map, then lets the operator generate,
customize, and save ASCII, Mixed, or image-backed headers. Drafts stay in
memory until Apply writes ``.yoke/board-art`` and rebuilds the board. Rendering
and persistence live in :mod:`onboard_wizard_board_art`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_wizard_board_art as art
from yoke_cli.config import onboard_wizard_board_art_steps as board_art_steps
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import WizardApplyError
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_FINISH,
    STEP_PROJECT,
    SelectionRow,
)
from yoke_contracts.project_contract.board_art import MAX_ART_WORD_LEN


class BoardArtFlow:
    def _init_board_art_state(self) -> None:
        from yoke_contracts.project_contract.board_art import resolve_project_art_word

        if not self.result.board_art_word:
            self.result.board_art_word = resolve_project_art_word(
                self.result.project_name or "",
                slug=self.result.project_slug,
                short_code=self.result.project_public_item_prefix,
            )
        if not self.result.board_art_seed:
            self.result.board_art_seed = (
                self.result.project_slug
                or self.result.project_name
                or self.result.board_art_word
                or "yoke"
            )
        # Per-draft scratch: the header currently being previewed.
        self._art_kind = ""
        self._art_attempt = 0
        self._art_word: str | None = None  # custom text; None = default word
        self._art_variant: Any = None
        self._art_image_path: str | None = None
        self._art_image_column: str | None = None

    def _board_art_view(self, step, builder, on_select):
        from yoke_cli.config.onboard_wizard_app import _View
        return _View(step, builder, on_select)

    def _current_art_word(self) -> str:
        if self._art_word is not None:
            return self._art_word
        return self.result.board_art_word or ""

    def _goto_board_art_intro(self) -> None:
        self._init_board_art_state()
        self._goto(self._selection_view(
            STEP_PROJECT,
            "Give your board a face.",
            "Every project gets a live status board — a progress map that fills "
            "in as work moves, topped with headers you design.",
            board_art_steps.BOARD_ART_INTRO_ROWS,
            self._on_board_art_intro,
        ))

    def _on_board_art_intro(self, _choice: str) -> None:
        self._goto_board_art_map_preview()

    def _goto_board_art_map_preview(self, *, replace_current: bool = False) -> None:
        rendered = art.render_master_map(self.result.board_art_word or "")
        rows = [
            SelectionRow(
                "continue", "Looks good — continue",
                f'spells "{self.result.board_art_word}"',
            ),
            SelectionRow("edit", "Edit the letters", f"up to {MAX_ART_WORD_LEN}"),
        ]
        view = self._board_art_view(
            STEP_PROJECT,
            lambda: board_art_steps.art_screen_body(
                "Here's your progress map.",
                "Shown with example work — it fills in as your items move.",
                rendered, rows,
            ),
            self._on_board_art_map_preview,
        )
        if replace_current:
            self._replace_current(view)
        else:
            self._goto(view)

    def _on_board_art_map_preview(self, choice: str) -> None:
        if choice == "edit":
            self._goto_input(
                STEP_PROJECT, "What should the map spell?",
                f"Letters and numbers, up to {MAX_ART_WORD_LEN} — auto-uppercased.",
                placeholder=self.result.board_art_word or "",
                on_done=self._after_board_art_map_word,
            )
            self._board_art_map_input_view = self._history[-1]
            return
        self._goto_board_art_style()

    def _after_board_art_map_word(self, value: str) -> None:
        from yoke_contracts.project_contract.board_art import (
            normalize_master_map_word,
        )

        word = normalize_master_map_word(value)
        if word:
            self.result.board_art_word = word
        self._discard_board_art_input("_board_art_map_input_view")
        self._goto_board_art_map_preview(replace_current=True)

    def _goto_board_art_style(self) -> None:
        view = self._selection_view(
            STEP_PROJECT,
            "Now design a header.",
            "Make as many as you like — the board rotates between your map and "
            "your headers.",
            board_art_steps.BOARD_ART_STYLE_ROWS,
            self._on_board_art_style,
        )
        self._board_art_style_view = view
        self._goto(view)

    def _return_to_board_art_style(self) -> None:
        """Return to the actual style picker without stacking a copy of it."""
        target = getattr(self, "_board_art_style_view", None)
        for index in range(len(self._history) - 1, -1, -1):
            if self._history[index] is target:
                del self._history[index + 1:]
                self._render_current()
                return
        self._goto_board_art_style()

    def _on_board_art_style(self, choice: str) -> None:
        self._art_word = None
        self._art_attempt = 0
        self._art_image_column = None
        self._art_image_path = None
        if choice == "image":
            self._goto_board_art_image_input()
            return
        self._art_kind = "ASCII" if choice == "ascii" else "Mixed"
        self._generate_and_preview()

    def _goto_board_art_image_input(self, *, replace_current: bool = False) -> None:
        if replace_current and self._history:
            self._history.pop()
        self._goto_input(
            STEP_PROJECT, "Point at an image.",
            "PNG or JPG. Yoke turns it into an emoji mosaic.",
            placeholder="~/Pictures/logo.png",
            on_done=self._after_board_art_image_path,
            allow_placeholder=False,
        )
        self._board_art_image_input_view = self._history[-1]

    def _after_board_art_image_path(self, value: str) -> None:
        try:
            kind, variant, column = art.build_image(
                path=Path(value).expanduser(),
                word=self._current_art_word(),
                seed_text=self.result.board_art_seed,
                master_map_word=self.result.board_art_word or "",
            )
        except Exception as exc:  # noqa: BLE001 - clean retry view, never a traceback
            message = art.friendly_image_error(exc)
            self._replace_current(self._board_art_view(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    "Couldn't use that image.", message, [],
                    board_art_steps.BOARD_ART_IMAGE_RETRY_ROWS, ok=False,
                ),
                self._on_board_art_image_error,
            ))
            return
        self._art_kind = kind
        self._art_image_path = value
        self._art_image_column = column
        self._art_attempt = 0
        self._art_variant = variant
        self._goto_board_art_preview(replace_current=True)

    def _on_board_art_image_error(self, choice: str) -> None:
        if choice == "retry":
            self._goto_board_art_image_input(replace_current=True)
        else:
            self._return_to_board_art_style()

    def _generate_and_preview(self, *, replace_current: bool = False) -> None:
        self._art_variant = art.generate_variant(
            kind=self._art_kind,
            word=self._current_art_word(),
            seed_text=self.result.board_art_seed,
            attempt=self._art_attempt,
            image_column=self._art_image_column,
        )
        self._goto_board_art_preview(replace_current=replace_current)

    def _goto_board_art_preview(self, *, replace_current: bool = False) -> None:
        variant = self._art_variant
        is_image = self._art_image_column is not None
        title = art.preview_title(self._art_kind, is_image)
        meta = art.preview_meta(variant, self._art_image_path)
        rows = art.preview_rows(self._art_kind, is_image)
        view = self._board_art_view(
            STEP_PROJECT,
            lambda: board_art_steps.art_screen_body(title, meta, variant.text, rows),
            self._on_board_art_preview,
        )
        if replace_current:
            self._replace_current(view)
        else:
            self._goto(view)

    def _on_board_art_preview(self, choice: str) -> None:
        if choice == "save":
            self.result.board_art_variants.append(self._art_variant)
            self._goto_board_art_gallery()
        elif choice == "shuffle":
            self._art_attempt += 1
            self._generate_and_preview(replace_current=True)
        elif choice == "customize":
            self._goto_input(
                STEP_PROJECT, "What should the header say?",
                "Letters, numbers, and spaces — the art auto-fits the width.",
                placeholder=(self._art_word or self.result.board_art_word or ""),
                on_done=self._after_board_art_text,
            )
            self._board_art_text_input_view = self._history[-1]
        elif choice == "reimage":
            self._goto_board_art_image_input(replace_current=True)
        else:
            self._return_to_board_art_style()

    def _after_board_art_text(self, value: str) -> None:
        from yoke_contracts.project_contract.board_art import (
            normalize_header_art_word,
        )

        self._art_word = normalize_header_art_word(value) or None
        self._art_attempt = 0
        self._discard_board_art_input("_board_art_text_input_view")
        self._generate_and_preview(replace_current=True)

    def _goto_board_art_gallery(self) -> None:
        self._goto(self._board_art_view(
            STEP_PROJECT,
            lambda: board_art_steps.board_art_gallery_body(self.result.board_art_variants),
            self._on_board_art_gallery,
        ))

    def _on_board_art_gallery(self, choice: str) -> None:
        if choice == "continue" and self.result.board_art_variants:
            self._goto_finish()
        else:
            self._return_to_board_art_style()

    def _discard_board_art_input(self, attribute: str) -> None:
        target = getattr(self, attribute, None)
        if self._history and self._history[-1] is target:
            self._history.pop()

    def _board_art_after_apply(self, report: Any) -> bool:
        """Write the chosen art into the materialized checkout and show the payoff.

        Returns True when a payoff screen is now showing (so the caller must not
        exit). No saved variants, or no resolvable checkout, means there is
        nothing to do.
        """
        if not self.result.board_art_variants:
            return False
        repo_root = art.repo_root_from_report(report, self.result.project_checkout)
        if repo_root is None:
            return False
        try:
            art.write_board_art(
                repo_root, self.result.board_art_word or "",
                self.result.board_art_variants,
            )
            art.rebuild_board(repo_root)
        except Exception as exc:  # noqa: BLE001 - route through Apply recovery
            summary = self._mark_board_art_failed(report, exc)
            raise WizardApplyError(
                f"couldn't write your board art and initial BOARD.md: {exc}",
                failed_step=(
                    summary.get("failed_step")
                    or "project-write-board-art"
                ),
                report_path=(
                    summary.get("path") or getattr(self, "report_path", None)
                ),
                resume_command=(
                    summary.get("resume_command")
                    or getattr(self, "resume_command", None)
                    or onboard_apply_report.RESUME_COMMAND
                ),
            ) from exc
        self._goto_board_art_payoff()
        return True

    def _mark_board_art_failed(
        self,
        report: Any,
        exc: BaseException,
    ) -> dict[str, Any]:
        summary = report.get("apply_report") if isinstance(report, dict) else None
        path = (
            summary.get("path")
            if isinstance(summary, dict)
            else getattr(self, "report_path", None)
        )
        if not path:
            return {}
        try:
            return onboard_apply_report.fail_report_path(
                path, exc, action="project-write-board-art",
            )
        except Exception:  # noqa: BLE001 - failure screen can still show root cause
            return {
                "path": path,
                "resume_command": (
                    getattr(self, "resume_command", None)
                    or onboard_apply_report.RESUME_COMMAND
                ),
            }

    def _goto_board_art_payoff(self) -> None:
        rendered = art.render_master_map(self.result.board_art_word or "")
        count = len(self.result.board_art_variants)
        self._goto(self._board_art_view(
            STEP_FINISH,
            lambda: board_art_steps.board_art_payoff_body(rendered, count),
            self._on_board_art_payoff,
        ))

    def _on_board_art_payoff(self, _choice: str) -> None:
        self.exit()


__all__ = ["BoardArtFlow"]
