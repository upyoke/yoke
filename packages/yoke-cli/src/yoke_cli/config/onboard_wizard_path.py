"""Install-summary and PATH screens for the ``yoke onboard`` wizard.

The flow diagnoses PATH and queues an exact managed-shell-block plan. Review
shows the login and non-login/SSH writes; Apply performs and verifies them.
All screens remain in the Install stepper segment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import install_binding, path_doctor, path_repair_plan
from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import ACCENT, BRAND as _BRAND, DANGER
from yoke_cli.config.onboard_wizard_steps import selection_body
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_INSTALL,
    SelectionRow,
)

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


INSTALL_ROWS = [
    SelectionRow("continue", "Continue", ""),
    SelectionRow("quit", "Quit", "stop here"),
]

# The apply row is first so the safe, idempotent fix is the default.
PATH_FIX_ROWS = [
    SelectionRow(
        "fix",
        "Add Yoke and harness CLIs to PATH",
        "Review shows both shell files before Apply",
    ),
    SelectionRow("preview", "See exactly what changes", ""),
]

PATH_OK_ROWS = [
    SelectionRow("continue", "Continue", "your shell is ready"),
]


def _yoke_version() -> str:
    return (
        install_binding.distribution_version(source_value="source checkout")
        or "unknown version"
    )


def _heading(title: str, subtitle: str) -> list[Static]:
    return [
        Static(title, classes="onboard-title"),
        Static(subtitle, classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
    ]


def _resolution_lines(label: str, resolved: list[Any]) -> list[Static]:
    """Render one tool-resolution group: ``✓ name → path`` (green) when the tool
    resolves, ``✗ name  not on PATH`` (red) when it does not."""
    marks = glyphs()
    lines: list[Static] = [Static(label, classes="onboard-plan-line")]
    for res in resolved:
        name = escape(res.name)
        if res.path:
            text = (
                f"  [{ACCENT}]{marks.ok} {name:<7} {marks.arrow} {escape(res.path)}[/]"
            )
        else:
            text = f"  [{DANGER}]{marks.fail} {name:<7} not on PATH[/]"
        lines.append(Static(text, classes="onboard-plan-line"))
    return lines


def _shadowing_lines(diagnosis: path_doctor.PathDiagnosis) -> list[Static]:
    warnings = []
    for label, winner in (
        ("This shell", diagnosis.yoke_shadowed_by),
        ("A new Terminal login shell", diagnosis.future_yoke_shadowed_by),
        ("An SSH command", diagnosis.ssh_yoke_shadowed_by),
    ):
        if not winner:
            continue
        warnings.append(
            Static(
                f"[{DANGER}]![/] {label}: {escape(diagnosis.preferred_yoke_path)} "
                f"exists, but {escape(winner)} wins.",
                classes="onboard-plan-line",
            )
        )
    if warnings:
        warnings.append(
            Static(
                "  The PATH fix moves Yoke's bin directory to the front and "
                "removes duplicate entries.",
                classes="onboard-plan-line",
            )
        )
    return warnings


def install_summary_body() -> list[Static]:
    widgets = _heading(
        f"{_BRAND} {_yoke_version()} is installed.",
        "Congrats! You're on your way to an eternity of Yoke.",
    )
    widgets.extend(selection_body("", "", INSTALL_ROWS))
    return widgets


def path_diagnosis_body(diagnosis: path_doctor.PathDiagnosis) -> list[Static]:
    if diagnosis.needs_fix:
        title = f"Put {_BRAND} and your harness CLIs on PATH."
        subtitle = (
            "The installer will keep login and non-login/SSH shells "
            "independently resolvable."
        )
        rows = PATH_FIX_ROWS
    else:
        title = f"{_BRAND} is already on your PATH."
        subtitle = "Nothing to change — Terminal and SSH can already find it."
        rows = PATH_OK_ROWS
    widgets = _heading(title, subtitle)
    widgets.extend(_resolution_lines("This shell sees:", diagnosis.current_resolved))
    widgets.extend(
        _resolution_lines("A new Terminal login shell sees:", diagnosis.future_resolved)
    )
    if diagnosis.ssh_resolved:
        widgets.extend(
            _resolution_lines("An SSH command sees:", diagnosis.ssh_resolved)
        )
    widgets.extend(_shadowing_lines(diagnosis))
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.extend(selection_body("", "", rows))
    return widgets


def path_preview_body(plan: dict[str, Any]) -> list[Static]:
    widgets = _heading(
        f"What {_BRAND} will write after you choose Apply.",
        "Review repeats these exact files and reasons before anything is written.",
    )
    for line in path_repair_plan.description_lines(plan):
        widgets.append(Static(f"  • {escape(line)}", classes="onboard-plan-line"))
    widgets.append(Static("", classes="onboard-spacer"))
    block = path_doctor.render_managed_block(tuple(plan["directories"]))
    widgets.extend(
        Static(f"  {line}", classes="onboard-plan-line") for line in block.splitlines()
    )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = [
        SelectionRow("apply", "Add it to Review", "Apply writes the files later"),
        SelectionRow("different", "Back", "return to the PATH summary"),
    ]
    widgets.extend(selection_body("", "", rows))
    return widgets


class PathFlow:
    """Install-summary + PATH steps that chain into the Connect flow."""

    def _start_front(self: _Shell) -> None:
        """Open the front of the wizard: install summary (post-install) or PATH."""
        if self._post_install:
            self._goto_install_summary()
            return
        self._goto_path_diagnosis()

    def _goto_install_summary(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(STEP_INSTALL, install_summary_body, self._on_install_summary))

    def _on_install_summary(self: _Shell, choice: str) -> None:
        if choice == "quit":
            self.cancelled = True
            self.exit_code = 0
            self.exit()
            return
        # "continue" advances into the PATH check.
        self._goto_path_diagnosis()

    def _goto_path_diagnosis(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        diagnosis = path_doctor.diagnose()
        self.result.path_repair = path_repair_plan.build(diagnosis)

        def builder() -> list[Static]:
            return path_diagnosis_body(diagnosis)

        view = _View(STEP_INSTALL, builder, self._on_path_diagnosis)
        self._path_diagnosis_view = view
        self._goto(view)

    def _on_path_diagnosis(self: _Shell, choice: str) -> None:
        if choice == "fix":
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
            self._start_connect()
            return
        if choice == "different":
            self._return_to_path_diagnosis()
            return

    def _return_to_path_diagnosis(self: _Shell) -> None:
        target = getattr(self, "_path_diagnosis_view", None)
        for index in range(len(self._history) - 1, -1, -1):
            if self._history[index] is target:
                del self._history[index + 1 :]
                self._render_current()
                return
        self._goto_path_diagnosis()


__all__ = [
    "INSTALL_ROWS",
    "PATH_FIX_ROWS",
    "PATH_OK_ROWS",
    "PathFlow",
    "install_summary_body",
    "path_diagnosis_body",
    "path_preview_body",
]
