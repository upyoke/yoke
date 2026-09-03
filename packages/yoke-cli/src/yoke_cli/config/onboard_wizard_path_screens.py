"""Install-summary and PATH screen builders for the ``yoke onboard`` wizard.

Pure functions that turn a PATH diagnosis or repair plan into the widgets a
step mounts. The preview screen is summary-first: one line per shell file
naming its effect, with the exact managed block behind a details toggle.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import install_binding, path_doctor, path_repair_plan
from yoke_cli.config.onboard_terminal import glyphs
from yoke_cli.config.onboard_wizard_palette import ACCENT, BRAND as _BRAND, DANGER
from yoke_cli.config.onboard_wizard_steps import selection_body
from yoke_cli.config.onboard_wizard_widgets import SelectionRow
from yoke_cli.config.path_state_contract import MANAGED_BEGIN, MANAGED_END


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


# Row values of the PATH preview screen.
PATH_PREVIEW_DETAILS_ROW = "details"
# The details toggle sits between Apply and Back, so a toggle re-render puts
# the cursor back on it.
PATH_PREVIEW_DETAILS_INDEX = 1


def path_preview_rows(
    plan: dict[str, Any], *, apply_now: bool, show_details: bool,
) -> list[SelectionRow]:
    if apply_now:
        apply_row = SelectionRow("apply", "Apply", "write the shell files now")
    else:
        apply_row = SelectionRow(
            "apply", "Add it to Review", "Apply writes the files later"
        )
    block_lines = len(path_doctor.render_managed_block(tuple(plan["directories"])).splitlines())
    if show_details:
        details_row = SelectionRow(
            PATH_PREVIEW_DETAILS_ROW, "Hide details", "back to the summary"
        )
    else:
        details_row = SelectionRow(
            PATH_PREVIEW_DETAILS_ROW,
            "Show details",
            f"the exact {block_lines}-line block each file gets",
        )
    return [
        apply_row,
        details_row,
        SelectionRow("different", "Back", "return to the PATH summary"),
    ]


def path_preview_body(
    plan: dict[str, Any],
    *,
    apply_now: bool = False,
    show_details: bool = False,
    initial: int = 0,
) -> list[Static]:
    """Summary first: one line per file naming its effect, the block behind a toggle."""
    if apply_now:
        title = f"Review the shell files {_BRAND} will write now."
        subtitle = "Apply updates login and non-login/SSH shells before the next step."
    else:
        title = f"What {_BRAND} will write after you choose Apply."
        subtitle = (
            "Review repeats these exact files and reasons before anything is written."
        )
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
    if show_details:
        widgets.append(Static("", classes="onboard-spacer"))
        block = path_doctor.render_managed_block(tuple(plan["directories"]))
        widgets.extend(
            Static(f"  {escape(line)}", classes="onboard-plan-line")
            for line in block.splitlines()
        )
    widgets.append(Static("", classes="onboard-spacer"))
    rows = path_preview_rows(plan, apply_now=apply_now, show_details=show_details)
    widgets.extend(selection_body("", "", rows, initial=initial))
    return widgets


def path_apply_error_body(message: str) -> list[Static]:
    widgets = _heading(
        "PATH files were written, but a shell probe failed.",
        "yoke is not yet resolvable in a new login or SSH shell.",
    )
    widgets.append(Static(escape(message), classes="onboard-plan-line"))
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(
        Static(
            "Recovery: rerun `yoke path fix`, then open a new terminal "
            "or `ssh host 'command -v yoke'`.",
            classes="onboard-note",
        )
    )
    return widgets


__all__ = [
    "INSTALL_ROWS",
    "PATH_FIX_ROWS",
    "PATH_OK_ROWS",
    "PATH_PREVIEW_DETAILS_INDEX",
    "PATH_PREVIEW_DETAILS_ROW",
    "install_summary_body",
    "path_apply_error_body",
    "path_diagnosis_body",
    "path_preview_body",
    "path_preview_rows",
]
