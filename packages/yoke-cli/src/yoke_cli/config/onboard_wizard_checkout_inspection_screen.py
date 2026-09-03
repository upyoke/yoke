"""The checkout inspection screen: what the fetched repository already holds.

Shown during the Project step, after the repository is fetched and before
Review, and only when the repository actually carries a Yoke operating layer —
a clean one has nothing to decide. Presentation only; the decision graph lives
in :mod:`onboard_wizard_flow_checkout_inspection`.
"""

from __future__ import annotations

from textual.widgets import Static

from yoke_cli.config import project_installed_layer as installed_layer
from yoke_cli.config.onboard_wizard_steps import verification_body
from yoke_cli.config.onboard_wizard_widgets import SelectionRow

LAYER_ROWS = [
    SelectionRow(
        installed_layer.LAYER_DECISION_REMOVE, "Remove them",
        "delete the Yoke files and commit, then install fresh",
    ),
    SelectionRow(
        installed_layer.LAYER_DECISION_KEEP, "Keep them",
        "install over what is already there",
    ),
]
FETCH_ERROR_ROWS = [
    SelectionRow("retry", "Try again", "fetch the repository again"),
    SelectionRow("choose-folder", "Choose another folder", "pick a new location"),
]

# What removing each kind of group would take, so the choice is made against
# the real consequence rather than a count.
_GROUP_EFFECTS = {
    installed_layer.KIND_DIRECTORY: "{rel} — {files}, whole folder",
    installed_layer.KIND_ADAPTERS: (
        "{rel} — {files}, Yoke's agents only; your own stay"
    ),
    installed_layer.KIND_FILE: "{rel}",
    installed_layer.KIND_MARKDOWN_BLOCK: (
        "{rel} — Yoke's block only, your own text stays"
    ),
    installed_layer.KIND_HOOK_ENTRIES: (
        "{rel} — {entries} of Yoke's, your other settings stay"
    ),
}


def inspection_lines(scan: installed_layer.InstalledLayerScan) -> list[str]:
    """One line per place the layer sits, naming what removing it would take."""
    return [
        _GROUP_EFFECTS[group.kind].format(
            rel=group.rel,
            files=_file_phrase(group.file_count),
            entries=_entry_phrase(group.file_count),
        )
        for group in scan.groups
    ]


def inspection_body(scan: installed_layer.InstalledLayerScan) -> list[Static]:
    """Report what the fetched repository holds, and ask what to do with it."""
    release = (
        f" installed by Yoke {scan.source_engine_release}"
        if scan.source_engine_release
        else ""
    )
    return verification_body(
        "This repository already has Yoke files in it.",
        f"{scan.root} carries a Yoke operating layer{release} — "
        f"{_file_phrase(scan.file_count)}. Removing them commits the deletion "
        "first, so the install that follows starts from a clean repository.",
        inspection_lines(scan),
        LAYER_ROWS,
        ok=False,
    )


def _file_phrase(count: int) -> str:
    return "1 file" if count == 1 else f"{count} files"


def _entry_phrase(count: int) -> str:
    return "1 hook entry" if count == 1 else f"{count} hook entries"


__all__ = [
    "FETCH_ERROR_ROWS",
    "LAYER_ROWS",
    "inspection_body",
    "inspection_lines",
]
