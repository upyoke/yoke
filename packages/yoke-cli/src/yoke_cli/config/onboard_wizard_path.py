"""Install-summary and PATH screens for the ``yoke onboard`` wizard.

A mixin consumed by :class:`onboard_wizard_app.OnboardWizardApp`, mirroring the
shape of :class:`onboard_wizard_flow.WizardFlow`. It fronts the wizard so the
installer hand-off and onboarding read as one app:

* a post-install summary shown only when the installer launched the wizard
  (``--post-install``), and
* a PATH diagnosis driven by :mod:`yoke_cli.config.path_doctor`, followed by a
  preview + consent screen that writes the managed PATH block and a verified
  screen that confirms a fresh login shell can find Yoke.

All of these screens highlight the ``install`` segment of the stepper — PATH
setup is part of installation, not its own step. They chain into the Account
step via ``_start_connect`` (the deployment-destination picker in
``onboard_wizard_flow_destination``) once the operator advances or skips, so
the rest of onboarding is unchanged. The mixin holds the PATH decision graph
only — no Textual plumbing and no report assembly.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import path_doctor
from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import ACCENT, BRAND as _BRAND, DANGER
from yoke_cli.config.onboard_wizard_steps import selection_body
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_INSTALL,
    SelectionRow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View

_PACKAGE_NAME = "yoke-cli"


class _Shell(Protocol):  # pragma: no cover - structural typing only
    _post_install: bool

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _start_connect(self) -> None: ...


# Install-summary choices.
INSTALL_ROWS = [
    SelectionRow("continue", "Continue", ""),
    SelectionRow("quit", "Quit", "stop here"),
]

# PATH diagnosis choices when a fix is needed. The add/apply row is the default
# selection (first row) per the default-Yes spirit.
PATH_FIX_ROWS = [
    SelectionRow("fix", "Add yoke to my PATH", "updates your shell startup file"),
    SelectionRow("preview", "See exactly what changes", ""),
    SelectionRow("skip", "Skip", ""),
]

# PATH diagnosis continue row when nothing needs fixing.
PATH_OK_ROWS = [
    SelectionRow("continue", "Continue", "your shell is ready"),
]

# PATH verified continue row, shown after the managed block is written. The
# next screen is the deployment-destination picker, so the caption names the
# choice rather than assuming a hosted sign-in.
PATH_VERIFIED_ROWS = [
    SelectionRow("continue", "Continue", "choose where your Yoke lives"),
]


def _yoke_version() -> str:
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.1.0"


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
            text = f"  [{ACCENT}]{marks.ok} {name:<7} {marks.arrow} {escape(res.path)}[/]"
        else:
            text = f"  [{DANGER}]{marks.fail} {name:<7} not on PATH[/]"
        lines.append(Static(text, classes="onboard-plan-line"))
    return lines


def install_summary_body() -> list[Static]:
    widgets = _heading(
        f"{_BRAND} {_yoke_version()} is installed.",
        "Congrats! You're on your way to an eternity of Yoke.",
    )
    widgets.extend(selection_body("", "", INSTALL_ROWS))
    return widgets


def path_diagnosis_body(diagnosis: path_doctor.PathDiagnosis) -> list[Static]:
    if diagnosis.needs_fix:
        title = f"Add {_BRAND} to your PATH."
        subtitle = (
            f"Yoke lives in {escape(diagnosis.tool_bin_dir)} "
            f"(your {escape(diagnosis.current_shell)} shell)."
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
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.extend(selection_body("", "", rows))
    return widgets


def path_preview_body(
    tool_bin_dir: str,
    startup_file: str,
    ssh_startup_file: str | None = None,
) -> list[Static]:
    files = [startup_file]
    if ssh_startup_file and ssh_startup_file not in files:
        files.append(ssh_startup_file)
    widgets = _heading(
        f"What {_BRAND} adds to your shell files.",
        "These lines go in once — re-running never duplicates them.",
    )
    widgets.extend(
        Static(f"  • {escape(path)}", classes="onboard-plan-line")
        for path in files
    )
    widgets.append(Static("", classes="onboard-spacer"))
    block = path_doctor.render_managed_block(tool_bin_dir)
    widgets.extend(
        Static(f"  {line}", classes="onboard-plan-line") for line in block.splitlines()
    )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = [
        SelectionRow("apply", "Add it", "writes the files above"),
        SelectionRow("different", "Choose a different file", ""),
        SelectionRow("skip", "Skip", ""),
    ]
    widgets.extend(selection_body("", "", rows))
    return widgets


def path_verified_body(
    startup_files: list[str],
    resolved: list[Any],
    ssh_resolved: list[Any] | None = None,
) -> list[Static]:
    marks = glyphs()
    widgets = _heading(f"Added {_BRAND} to your PATH.", "")
    for startup_file in startup_files:
        widgets.append(
            Static(
                f"[{ACCENT}]{marks.ok}[/] Wrote the managed block to {escape(startup_file)}",
                classes="onboard-plan-line",
            )
        )
    widgets.append(
        Static(f"[{ACCENT}]{marks.ok}[/] Checked a fresh login shell:", classes="onboard-plan-line")
    )
    for res in resolved:
        if res.path:
            widgets.append(
                Static(f"      {res.name} {marks.arrow} {res.path}", classes="onboard-subtitle")
            )
    if ssh_resolved:
        widgets.append(
            Static(f"[{ACCENT}]{marks.ok}[/] Checked an SSH command:", classes="onboard-plan-line")
        )
        for res in ssh_resolved:
            if res.path:
                widgets.append(
                    Static(f"      {res.name} {marks.arrow} {res.path}", classes="onboard-subtitle")
                )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(
        Static(f"Your next terminal will find {_BRAND}.", classes="onboard-title")
    )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.extend(selection_body("", "", PATH_VERIFIED_ROWS))
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

        def builder() -> list[Static]:
            return path_diagnosis_body(diagnosis)

        self._goto(_View(STEP_INSTALL, builder, self._on_path_diagnosis))

    def _on_path_diagnosis(self: _Shell, choice: str) -> None:
        if choice == "fix":
            self._apply_path_fix()
            return
        if choice == "preview":
            self._goto_path_preview()
            return
        # "skip" or "continue" both advance into the rest of onboarding.
        self._start_connect()

    def _goto_path_preview(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        diagnosis = path_doctor.diagnose()
        bindir = diagnosis.tool_bin_dir
        startup = diagnosis.startup_file
        ssh_startup = (
            diagnosis.ssh_startup_file if diagnosis.ssh_needs_fix else None
        )

        def builder() -> list[Static]:
            return path_preview_body(bindir, startup, ssh_startup)

        self._goto(_View(STEP_INSTALL, builder, self._on_path_preview))

    def _on_path_preview(self: _Shell, choice: str) -> None:
        if choice == "apply":
            self._apply_path_fix()
            return
        # "different" and "skip" both leave the startup file untouched for now;
        # an alternate-file picker is a later refinement.
        self._start_connect()

    def _apply_path_fix(self: _Shell) -> None:
        diagnosis = path_doctor.diagnose()
        shell = diagnosis.current_shell
        bindir = diagnosis.tool_bin_dir
        startup = Path(diagnosis.startup_file)
        written = [str(startup)]
        path_doctor.apply_fix(startup, bindir)
        if diagnosis.ssh_needs_fix and diagnosis.ssh_startup_file:
            ssh_startup = Path(diagnosis.ssh_startup_file)
            if ssh_startup != startup:
                path_doctor.apply_fix(ssh_startup, bindir)
                written.append(str(ssh_startup))
        resolved = path_doctor.verify_fresh_login(shell)
        ssh_resolved = path_doctor.verify_ssh_command(shell)
        self._goto_path_verified(written, resolved, ssh_resolved)

    def _goto_path_verified(
        self: _Shell,
        startup: list[str],
        resolved: list[Any],
        ssh_resolved: list[Any] | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def builder() -> list[Static]:
            return path_verified_body(startup, resolved, ssh_resolved)

        self._goto(_View(STEP_INSTALL, builder, self._on_path_verified))

    def _on_path_verified(self: _Shell, _choice: str) -> None:
        self._start_connect()


__all__ = [
    "INSTALL_ROWS",
    "PATH_FIX_ROWS",
    "PATH_OK_ROWS",
    "PATH_VERIFIED_ROWS",
    "PathFlow",
    "install_summary_body",
    "path_diagnosis_body",
    "path_preview_body",
    "path_verified_body",
]
