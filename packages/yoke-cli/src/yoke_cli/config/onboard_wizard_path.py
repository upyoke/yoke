"""PATH-readiness flow for the ``yoke onboard`` wizard.

The flow diagnoses PATH and can apply its exact managed-shell-block plan in one
confirmation. The optional preview shows the complete login and non-login/SSH
writes before that same immediate repair. All screens remain in the Install
stepper segment; their builders live in :mod:`onboard_wizard_path_screens`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from textual.widgets import Static

from yoke_cli.config import path_doctor, path_repair_plan
from yoke_cli.config.onboard_wizard_path_screens import (
    PATH_FIX_ROWS,
    PATH_OK_ROWS,
    path_apply_error_body,
    path_diagnosis_body,
    path_preview_body,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_INSTALL

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    _post_install: bool
    _history: list["_View"]
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _render_current(self) -> None: ...
    def _start_connect(self) -> None: ...
    def _apply_path_now(self) -> bool: ...


class PathFlow:
    """PATH readiness and repair steps that chain into the Connect flow."""

    def _start_front(self: _Shell) -> None:
        """Begin directly at PATH readiness, including after installation."""
        self._goto_path_diagnosis()

    def _goto_path_diagnosis(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        diagnosis = path_doctor.diagnose()
        self.result.path_repair = path_repair_plan.build(diagnosis)

        def builder() -> list[Static]:
            return path_diagnosis_body(
                diagnosis,
                installed_version=self._post_install,
            )

        view = _View(STEP_INSTALL, builder, self._on_path_diagnosis)
        self._path_diagnosis_view = view
        self._goto(view)

    def _on_path_diagnosis(self: _Shell, choice: str) -> None:
        if choice == "fix":
            if self._apply_path_now():
                self._start_connect()
            return
        if choice == "preview":
            self._goto_path_preview()
            return
        # An all-clear diagnosis has only "continue".
        self._start_connect()

    def _goto_path_preview(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        plan = self.result.path_repair or path_repair_plan.build(path_doctor.diagnose())
        self.result.path_repair = plan

        def builder() -> list[Static]:
            return path_preview_body(plan)

        self._goto(_View(STEP_INSTALL, builder, self._on_path_preview))

    def _on_path_preview(self: _Shell, choice: str) -> None:
        if choice == "apply":
            if self._apply_path_now():
                self._start_connect()
            return
        if choice == "different":
            self._return_to_path_diagnosis()
            return

    def _apply_path_now(self: _Shell) -> bool:
        from yoke_cli.config import onboard_apply_path

        plan = self.result.path_repair
        if not plan:
            return True
        report: dict[str, Any] = {}
        try:
            onboard_apply_path.apply(plan, progress=None, report=report)
        except OSError as exc:
            self._goto_path_apply_error(
                f"Could not write the shell files ({exc}). "
                "Check permissions, then Apply again or run `yoke path fix`."
            )
            return False
        outcome = report.get("path_repair") or {}
        self.result.path_repair = {**plan, **outcome}
        if outcome.get("login_verified") and outcome.get("ssh_verified"):
            return True
        missing = [
            name
            for name, ok in (
                ("login", outcome.get("login_verified")),
                ("SSH", outcome.get("ssh_verified")),
            )
            if not ok
        ]
        self._goto_path_apply_error(
            "Could not resolve yoke/uv in a "
            + " or ".join(missing)
            + " shell after writing. "
            "Rerun `yoke path fix`, then open a new terminal "
            "or `ssh host 'command -v yoke'`."
        )
        return False

    def _goto_path_apply_error(self: _Shell, message: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(STEP_INSTALL, lambda: path_apply_error_body(message)))

    def _return_to_path_diagnosis(self: _Shell) -> None:
        target = getattr(self, "_path_diagnosis_view", None)
        for index in range(len(self._history) - 1, -1, -1):
            if self._history[index] is target:
                del self._history[index + 1 :]
                self._render_current()
                return
        self._goto_path_diagnosis()


__all__ = [
    "PATH_FIX_ROWS",
    "PATH_OK_ROWS",
    "PathFlow",
    "path_apply_error_body",
    "path_diagnosis_body",
    "path_preview_body",
]
