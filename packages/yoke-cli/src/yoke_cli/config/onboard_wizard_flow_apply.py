"""Apply phase: the live Applying screen and its success/failure/recovery views.

``WizardFlow._on_confirm`` hands a confirmed Apply to :meth:`ApplyFlow._start_apply`.
Apply is a blocking network/git transaction, so it runs in a worker thread while
the event loop keeps painting the Applying screen; each ``build_report`` progress
event flips one row in place. The worker's outcome routes to a success, board-art
payoff, or in-TUI failure/recovery screen — never a mid-mutation teardown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.widgets import Static

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.github_repository_create import REPOSITORY_CONTENT_MISMATCH
from yoke_cli.config.onboard_terminal import plain_text
from yoke_cli.config.onboard_error_friendly import (
    friendly_permission_error,
    friendly_publish_error,
)
from yoke_cli.config.onboard_wizard import WizardApplyError
from yoke_cli.config.onboard_wizard_widgets import STEP_FINISH


class ApplyFlow:
    """Mixin: drive Apply off the event loop and render its result screens."""

    # ── apply: live Applying screen driven by a worker thread ──────────

    def _start_apply(self) -> None:
        """Show the Applying screen and run the apply off the event loop.

        Running Apply inline froze the Review screen for its whole duration;
        instead it runs in a worker thread so the loop keeps painting, and each
        build_report progress event flips one Applying row in place.
        """
        self._apply_steps = self._applying_step_model()
        self._applying = True
        self._goto_applying()
        self.run_worker(
            self._apply_in_thread, thread=True, exclusive=True,
            group="onboard-apply",
        )

    def _applying_step_model(self) -> list:
        from yoke_cli.config import onboard_apply_report

        return [
            {
                "step_id": ref.step_id,
                "action": ref.action,
                "target": ref.target,
                "label": ref.label,
                "status": "pending",
            }
            for ref in onboard_apply_report.steps_from_preview(self._review_plan)
        ]

    def _goto_applying(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        # Replace (not push) the Review view: the Applying screen is non-
        # interactive, so leaving it in history would let Esc land on a dead
        # screen. Replacing keeps "Change answers" landing one real step back.
        self._replace_current(_View(STEP_FINISH, self._build_applying, None))

    def _build_applying(self) -> list:
        return steps.apply_progress_body(self._apply_steps)

    def _apply_in_thread(self) -> None:
        """Worker-thread body: run the apply, then hand the outcome to the loop."""
        kwargs = self.result.build_report_kwargs(apply=True, check_identity=True)
        if self._resume_run_id and self._resume_payload is not None:
            kwargs["resume_run_id"] = self._resume_run_id
            kwargs["resume_payload"] = self._resume_payload
        try:
            report = self._apply_report(kwargs, self._thread_progress)
        except Exception as exc:  # noqa: BLE001 - every failure routes to the screen
            self.call_from_thread(self._finish_apply, None, exc)
            return
        self.call_from_thread(self._finish_apply, report, None)

    def _thread_progress(self, action: str, target: str, status: str) -> None:
        # Runs on the worker thread; marshal the row update onto the event loop.
        self.call_from_thread(self._set_apply_step_status, action, target, status)

    def _set_apply_step_status(self, action: str, target: str, status: str) -> None:
        step = self._match_apply_step(action, target)
        if step is None:
            return
        step["status"] = status
        try:
            row = self.query_one(f"#applystep-{step['step_id']}", Static)
        except Exception:  # noqa: BLE001 - body not mounted yet; model still updates
            return
        text = steps.apply_step_line(step)
        if getattr(self, "_plain_glyphs", False):
            text = plain_text(text)
        row.update(text)

    def _match_apply_step(self, action: str, target: str) -> dict | None:
        for step in self._apply_steps:
            if step.get("action") != action:
                continue
            if target and step.get("target") != target:
                continue
            return step
        return None

    def _finish_apply(self, report: Any, exc: BaseException | None) -> None:
        """Main-thread continuation after the apply worker finishes."""
        self._applying = False
        if exc is not None:
            self._show_apply_failure(exc)
            return
        self.exit_code = 0
        self.last_error = None
        self.failed_step = None
        self.resume_command = None
        self._resume_run_id = None
        self._resume_payload = None
        if isinstance(report, dict):
            summary = report.get("apply_report")
            if isinstance(summary, dict):
                self.report_path = summary.get("path")
        # When the operator designed board art, materialize it into the freshly
        # created checkout and show the payoff instead of exiting straight away.
        try:
            if self._board_art_after_apply(report):
                return
        except Exception as board_art_exc:  # noqa: BLE001 - route to recovery
            self._show_apply_failure(board_art_exc)
            return
        self._goto_apply_success()

    def _show_apply_failure(self, exc: BaseException) -> None:
        self.exit_code = 1
        if isinstance(exc, WizardApplyError):
            self.failed_step = exc.failed_step
            self.report_path = exc.report_path
            self.resume_command = exc.resume_command
        self.last_error = friendly_publish_error(
            friendly_permission_error(str(exc))
        )
        self._goto_apply_failure()

    def _goto_apply_failure(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._replace_current(
            _View(STEP_FINISH, self._build_apply_failure, self._on_apply_failure)
        )

    def _build_apply_failure(self) -> list:
        run_id = _apply_report_run_id(self.report_path)
        return steps.apply_failure_body(
            self.last_error or "Onboarding did not finish.",
            failed_step=self.failed_step,
            report_path=self.report_path,
            resume_command=self.resume_command,
            retryable=_apply_error_retryable(self.last_error),
            can_resume=_can_resume_run(run_id),
            can_use_different_folder=(
                _preservable_checkout_path(run_id) is not None
            ),
        )

    def _on_apply_failure(self, choice: str) -> None:
        if choice == "retry":
            self._start_apply()
            return
        if choice == "resume":
            self._resume_apply_from_report()
            return
        if choice == "different-folder":
            self._goto_apply_different_folder()
            return
        if choice == "back":
            # The Applying screen replaced Review in history, so one step back
            # lands on the step before Review where answers can be changed.
            self._resume_run_id = None
            self._resume_payload = None
            import asyncio

            asyncio.ensure_future(self.action_back())
            return
        self.exit_code = 1
        self.exit()

    def _resume_apply_from_report(self) -> None:
        from yoke_cli.config import onboard_apply_resume

        run_id = _apply_report_run_id(self.report_path)
        if not run_id:
            self._show_apply_recovery_error("the saved apply report could not be found")
            return
        try:
            payload = onboard_apply_resume.load_payload(run_id)
            onboard_apply_resume.load_snapshot(run_id)
        except onboard_apply_resume.OnboardApplyResumeError as exc:
            self._show_apply_recovery_error(exc)
            return
        self._resume_run_id = run_id
        self._resume_payload = payload
        self._start_apply()

    def _goto_apply_different_folder(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_FINISH,
                self._build_apply_different_folder,
                self._on_apply_different_folder,
            )
        )

    def _build_apply_different_folder(self) -> list:
        run_id = _apply_report_run_id(self.report_path)
        return steps.apply_different_folder_body(
            report_path=self.report_path,
            checkout_path=_preservable_checkout_path(run_id),
        )

    def _on_apply_different_folder(self, choice: str) -> None:
        if choice == "cancel":
            import asyncio

            asyncio.ensure_future(self.action_back())
            return
        if choice != "confirm-different-folder":
            return
        from yoke_cli.config import onboard_apply_resume

        run_id = _apply_report_run_id(self.report_path)
        if not run_id:
            self._show_apply_recovery_error("the saved apply report could not be found")
            return
        try:
            result = onboard_apply_resume.preserve_checkout_for_new_target(
                run_id, confirmed=True,
            )
        except onboard_apply_resume.OnboardApplyResumeError as exc:
            self._show_apply_recovery_error(exc)
            return
        self.report_path = str(result.get("report_path") or self.report_path or "")
        self._resume_run_id = None
        self._resume_payload = None
        if len(self._history) > 1:
            self._history.pop()
        import asyncio

        asyncio.ensure_future(self.action_back())

    def _show_apply_recovery_error(self, exc: BaseException | str) -> None:
        self.last_error = friendly_publish_error(
            friendly_permission_error(str(exc))
        )
        self._goto_apply_failure()

    def _goto_apply_success(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._replace_current(
            _View(STEP_FINISH, self._build_apply_success, self._on_apply_success)
        )

    def _build_apply_success(self) -> list:
        return steps.apply_success_body(self.report_path)

    def _on_apply_success(self, choice: str) -> None:
        if choice == "show-report":
            return
        self.exit_code = 0
        self.exit()


def _apply_error_retryable(message: str | None) -> bool:
    """Whether re-running the same apply could plausibly change the outcome.

    A repo name that already exists with content fails identically on retry — the
    user must change the name — so that case offers no "Try again". Everything
    else (transient network, a late TOCTOU collision detected at create) may
    succeed on a second attempt.
    """
    text = (message or "").lower()
    if (
        "already exists and has content" in text
        or REPOSITORY_CONTENT_MISMATCH in text
    ):
        return False
    return True


def _apply_report_run_id(report_path: str | None) -> str | None:
    if not report_path:
        return None
    from yoke_cli.config import onboard_apply_resume

    try:
        name = Path(str(report_path)).expanduser().name
        return onboard_apply_resume.normalize_run_id(name)
    except onboard_apply_resume.OnboardApplyResumeError:
        return None


def _can_resume_run(run_id: str | None) -> bool:
    if not run_id:
        return False
    from yoke_cli.config import onboard_apply_resume

    try:
        onboard_apply_resume.load_snapshot(run_id)
    except onboard_apply_resume.OnboardApplyResumeError:
        return False
    return True


def _preservable_checkout_path(run_id: str | None) -> str | None:
    if not run_id:
        return None
    from yoke_cli.config import onboard_apply_resume

    try:
        return onboard_apply_resume.preservable_checkout_path(run_id)
    except onboard_apply_resume.OnboardApplyResumeError:
        return None


__all__ = ["ApplyFlow"]
