"""Automatic Install checks and error recovery for the setup wizard."""

from __future__ import annotations

import asyncio
from typing import Any

from yoke_cli.config import onboard_apply_path, path_doctor, path_repair_plan
from yoke_cli.config.onboard_wizard_path_screens import (
    path_apply_error_body,
    path_apply_error_prompt,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_INSTALL
from yoke_cli.config.setup_run_facts import PATH_CHANGED_FILES
from yoke_cli.config.onboard_wizard_project_fields import reset_project_fields


class PathFlow:
    """Run Install off the UI thread; mount a view only when it needs attention."""

    def _start_front(self) -> None:
        self._checking = True
        self._checking_blocks_quit = True
        self.run_worker(self._run_install(), exclusive=True, group="onboard-install")

    async def _run_install(self) -> None:
        plan, error = await asyncio.to_thread(self._check_install)
        self._finish_install(plan, error)

    def _finish_install(self, plan: dict[str, Any], error: str) -> None:
        self._checking = False
        self._checking_blocks_quit = False
        previous = self.result.path_repair or {}
        # A later pass finds the shell files already repaired; the run fact
        # keeps the files this run changed so the done screen still names them.
        changed = sorted(
            {
                *(self._run_facts.get(PATH_CHANGED_FILES) or []),
                *previous.get("changed_files", []),
                *plan.get("changed_files", []),
            }
        )
        if changed:
            self._run_facts.record(PATH_CHANGED_FILES, changed)
        plan["changed_files"] = changed
        self.result.path_repair = plan
        if self._history and self._history[-1].step == STEP_INSTALL:
            self._history.pop()
        if error:
            self._goto_path_apply_error(error)
        else:
            if (
                not self._project_mode_preset
                and not self._stored_project_checkouts
                and not getattr(self, "_restored_projects", None)
            ):
                self._goto_project_mode(on_selected=self._remember_project_mode)
            else:
                self._start_connect()

    def _remember_project_mode(self, mode: str) -> None:
        reset_project_fields(self.result)
        self._project_preset_attempted = False
        self.result.project_mode = mode
        self._project_mode_preset = True
        self._start_connect()

    def _check_install(self) -> tuple[dict[str, Any], str]:
        plan: dict[str, Any] = {}
        report: dict[str, Any] = {}
        try:
            diagnosis = path_doctor.diagnose()
            plan = path_repair_plan.build(diagnosis)
            if plan.get("targets"):
                onboard_apply_path.apply(plan, progress=None, report=report)
                plan = report["path_repair"]
                resolved = plan.get("login_resolved") or {}
            else:
                resolved = {row.name: row.path for row in diagnosis.future_resolved}
                plan = {**plan, "login_verified": True, "login_resolved": resolved}
            missing = [tool for tool in path_doctor.TOOLS if not resolved.get(tool)]
            if missing:
                raise RuntimeError(
                    "install_required_tool_missing: a fresh login shell cannot find "
                    + ", ".join(missing)
                    + ". Run the installer again: curl -fsSL https://upyoke.com/install | sh; "
                    "then open a new terminal and retry Install."
                )
            if not plan.get("login_verified"):
                failures = " ".join(
                    f"{row['shell']} {row['context']}: {row['reason']}; "
                    f"yoke -> {row['resolved'].get('yoke') or 'not found'}; "
                    f"{row['recovery']}"
                    for row in plan.get("contexts", []) if row["needs_fix"]
                )
                raise RuntimeError(
                    "fresh_login_path_unresolved: shell repair did not verify Yoke. "
                    + failures
                    + " Correct remaining shell configuration or the current terminal's PATH, "
                    "then open a new terminal and retry Install. "
                    "Repeating unchanged owned-block repair cannot fix user-owned overrides."
                )
            return plan, ""
        except Exception as exc:  # noqa: BLE001 - all failures need a recovery view
            plan = report.get("path_repair") or plan
            plan = {**plan, "login_verified": False}
            return plan, (
                f"install_check_failed: {exc} "
                "Fix the named cause, then retry Install or run `yoke setup` again."
            )

    def _goto_path_apply_error(self, message: str) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        prompt = path_apply_error_prompt(message, self.result.path_repair)
        self._goto(
            _View(prompt, self._retry_install, lambda: path_apply_error_body(prompt))
        )

    def _retry_install(self, choice: str) -> None:
        if choice == "retry" and not self._checking:
            self._start_front()


__all__ = ["PathFlow"]
