"""PATH-readiness screen builders for the ``yoke onboard`` wizard.

Pure functions that turn a PATH diagnosis or repair plan into the widgets a
step mounts. The readiness screen summarizes the affected files; its optional
preview shows the uv command before the one-confirmation repair.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import install_binding, path_doctor, path_repair_plan
from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import (
    ACCENT,
    BRAND as _BRAND,
    DANGER,
    DIM,
)
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow


# The apply row is first so the safe, idempotent fix is the default.
PATH_FIX_ROWS = [
    SelectionRow(
        "fix",
        "Add to PATH and continue",
        "uv updates shell configuration; verifies a fresh login shell",
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


def _tool_readiness_lines(diagnosis: path_doctor.PathDiagnosis) -> list[Static]:
    """One compact readiness line per tool, current-shell resolution only.

    ``yoke``/``uv``/``uvx`` are required — missing renders red. A harness CLI
    (Cursor, Codex, …) not on PATH is optional and neutral: it means the tool
    isn't installed, not that the PATH fix is broken.
    """
    marks = glyphs()
    optional = set(path_doctor.HARNESS_CLIS)
    lines: list[Static] = []
    for res in diagnosis.current_resolved:
        name = escape(res.name)
        if res.path:
            text = f"[{ACCENT}]{marks.ok} {name}[/]"
        elif res.name in optional:
            text = f"[{DIM}]{marks.bullet} {name}  not installed (optional)[/]"
        else:
            text = f"[{DANGER}]{marks.fail} {name}  not on PATH[/]"
        lines.append(Static(text, classes="onboard-plan-line"))
    return lines


def _shell_files_summary(diagnosis: path_doctor.PathDiagnosis) -> list[Static]:
    """Name the delegated shell update rather than predicting uv's writes."""
    if not diagnosis.needs_fix:
        return []
    return [Static("Will run uv tool update-shell", classes="onboard-plan-line")]


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
                "  Run uv tool update-shell and check startup files that override PATH.",
                classes="onboard-plan-line",
            )
        )
    return warnings


def path_diagnosis_body(
    diagnosis: path_doctor.PathDiagnosis,
    *,
    installed_version: bool = False,
) -> list[Static]:
    if diagnosis.needs_fix:
        title = f"Put {_BRAND} on PATH."
        subtitle = "uv will update your shell configuration."
        rows = PATH_FIX_ROWS
    else:
        title = f"{_BRAND} is already on your PATH."
        subtitle = "Nothing to change — a fresh login shell can already find it."
        rows = PATH_OK_ROWS
    widgets = _heading(title, subtitle)
    if installed_version:
        widgets.insert(
            0,
            Static(
                f"{_BRAND} {_yoke_version()} installed.",
                classes="onboard-note",
            ),
        )
    widgets.extend(_tool_readiness_lines(diagnosis))
    widgets.extend(_shadowing_lines(diagnosis))
    widgets.extend(_shell_files_summary(diagnosis))
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(rows))
    return widgets


# Row values of the PATH preview screen.
def path_preview_rows() -> list[SelectionRow]:
    return [
        SelectionRow("apply", "Add to PATH and continue", "write and verify now"),
        SelectionRow("different", "Back", "return to the PATH summary"),
    ]


def path_preview_body(
    plan: dict[str, Any],
) -> list[Static]:
    """Optional exact-change view reached from PATH readiness."""
    widgets = _heading(
        f"PATH setup for {_BRAND}.",
        "uv selects the shell files to update; Yoke verifies a fresh login shell.",
    )
    for line in path_repair_plan.description_lines(plan):
        widgets.append(Static(escape(line), classes="onboard-plan-line"))
    widgets.append(
        Static("Open a new terminal after setup.", classes="onboard-plan-line")
    )
    widgets.append(SelectionList(path_preview_rows()))
    return widgets


def path_apply_error_body(message: str) -> list[Static]:
    widgets = _heading(
        "Shell PATH setup needs attention.",
        "yoke must resolve in a fresh login shell.",
    )
    widgets.append(Static(f"Cause: {escape(message)}", classes="onboard-plan-line"))
    widgets.append(Static("What to do", classes="onboard-title"))
    widgets.append(
        Static(
            "Run `uv tool update-shell`, then open a new terminal.",
            classes="onboard-plan-line",
        )
    )
    return widgets


__all__ = [
    "PATH_FIX_ROWS",
    "PATH_OK_ROWS",
    "path_apply_error_body",
    "path_diagnosis_body",
    "path_preview_body",
    "path_preview_rows",
]
