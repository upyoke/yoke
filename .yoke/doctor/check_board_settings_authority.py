"""HC-board-settings-authority: retired file/machine board settings must be gone.

Board appearance and scope live only in ``project-policy.settings.board``.
A leftover ``.yoke/board.json`` with settings keys, or a machine-config
``projects[].board`` object, is a regression against that hard cut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.project_contract.board_art.config_paths import board_config_path
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks._declare import self_project_checks

_BOARD_SETTING_KEYS = {f.name for f in BoardConfig.__dataclass_fields__.values()}
_HC = "HC-board-settings-authority"
_DESC = "Board settings live only in project-policy (no board.json / machine board)"


def hc_board_settings_authority(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """FAIL when retired board.json settings or machine board entries remain."""
    try:
        cfg = machine_config.load_config()
    except Exception as exc:  # noqa: BLE001 — doctor surface
        rec.record(_HC, _DESC, "FAIL", f"could not load machine config: {exc}")
        return

    problems: list[str] = []
    projects = cfg.get("projects") or []
    if isinstance(projects, list):
        for entry in projects:
            if not isinstance(entry, Mapping):
                continue
            checkout = entry.get("checkout")
            if "board" in entry:
                problems.append(
                    f"machine projects[].board present for {checkout!r}"
                )
            if not checkout:
                continue
            board_path = board_config_path(Path(str(checkout)).expanduser())
            if not board_path.is_file():
                continue
            try:
                raw = json.loads(board_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                problems.append(f"unreadable board.json at {board_path}")
                continue
            if isinstance(raw, Mapping) and any(
                key in _BOARD_SETTING_KEYS
                or str(key).startswith("art_weight_rainbow_")
                for key in raw
            ):
                problems.append(f"board.json settings remain at {board_path}")

    if problems:
        rec.record(_HC, _DESC, "FAIL", "; ".join(problems[:8]))
        return
    rec.record(
        _HC, _DESC, "PASS",
        "no retired board.json settings or machine board entries",
    )


PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "board-settings-authority",
        _DESC,
        hc_board_settings_authority,
    ),
)
