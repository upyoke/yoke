"""PATH-readiness screen builders for the ``yoke onboard`` wizard.

Pure functions that turn a PATH diagnosis or repair plan into the widgets a
step mounts. The readiness screen summarizes the affected files; its optional
preview shows the complete managed block before the one-confirmation repair.
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
from yoke_cli.config.path_state_contract import MANAGED_BEGIN, MANAGED_END


# The apply row is first so the safe, idempotent fix is the default.
PATH_FIX_ROWS = [
    SelectionRow(
        "fix",
        "Add to PATH and continue",
        "Writes and verifies the named shell files now",
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
    """Compact count + exact paths of the shell files the fix will touch."""
    files = []
    if diagnosis.login_needs_fix and diagnosis.startup_file:
        files.append(f"{escape(diagnosis.startup_file)} (login)")
    if diagnosis.ssh_needs_fix and diagnosis.ssh_startup_file:
        files.append(f"{escape(diagnosis.ssh_startup_file)} (SSH/non-login)")
    if not files:
        return []
    noun = "shell file" if len(files) == 1 else "shell files"
    return [
        Static(
            f"Will update {len(files)} {noun}: {', '.join(files)}",
            classes="onboard-plan-line",
        )
    ]


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


def path_diagnosis_body(
    diagnosis: path_doctor.PathDiagnosis,
    *,
    installed_version: bool = False,
) -> list[Static]:
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
    title = f"Exact PATH changes {_BRAND} will write."
    subtitle = "Add to PATH updates and verifies these shell files before continuing."
    widgets = _heading(title, subtitle)
    for line in path_repair_plan.description_lines(plan):
        widgets.append(Static(f"  • {escape(line)}", classes="onboard-plan-line"))
    widgets.append(
        Static(
            f"  • Each file gets one block between the {escape(MANAGED_BEGIN)} and "
            f"{escape(MANAGED_END)} markers; delete the block to undo.",
            classes="onboard-plan-line",
        )
    )
    widgets.append(Static("", classes="onboard-spacer"))
    block = path_doctor.render_managed_block(tuple(plan["directories"]))
    widgets.extend(
        Static(f"  {escape(line)}", classes="onboard-plan-line")
        for line in block.splitlines()
    )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(path_preview_rows()))
    return widgets


def path_apply_error_body(message: str) -> list[Static]:
    widgets = _heading(
        "PATH files were written, but a shell probe failed.",
        "yoke is not yet resolvable in a new login or SSH shell.",
    )
    widgets.append(Static(f"Cause: {escape(message)}", classes="onboard-plan-line"))
    widgets.append(Static("What to do", classes="onboard-title"))
    widgets.append(
        Static(
            "Rerun `yoke path fix`, then open a new terminal "
            "or `ssh host 'command -v yoke'`.",
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
