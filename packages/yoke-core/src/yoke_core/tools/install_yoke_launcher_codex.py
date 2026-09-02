"""Write the unattended posture into Codex's own ``config.toml``.

The TOML surgery lives in
:mod:`yoke_core.tools.install_yoke_launcher_codex_config`; this module is the
IO and the reporting around it. Codex reads no project-local config, so the
machine file is the only place its posture can live — including the
directory-trust entry for the checkout being installed, without which Codex
asks about the folder itself before it asks about anything in it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_core.tools.install_yoke_launcher_codex_config import (
    CodexConfigUnreadable,
    changed,
    plan,
    read_config_text,
)


def configure_codex_unattended_posture(
    *,
    checkout: Optional[Path] = None,
    config_path: Optional[Path] = None,
    stream=None,
) -> List[str]:
    """Set Codex's approval, sandbox, and trust keys; return what it reports.

    An empty list means nothing to say: Codex is absent, or already
    unattended.
    """
    target = config_path if config_path is not None else codex_config_path()
    out = stream if stream is not None else sys.stdout
    text = read_config_text(target)
    if text is None:
        return []
    try:
        updated, record = plan(text, str(checkout) if checkout else None)
    except CodexConfigUnreadable as exc:
        line = (
            f"codex: {target} is not valid TOML ({exc}); Codex reads no "
            "posture from it and will keep asking. Repair the file, then "
            "rerun the installer."
        )
        out.write(f"{line}\n")
        return [line]
    actions: List[str] = []
    if changed(record):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".yoke-tmp")
        try:
            tmp.write_text(updated, encoding="utf-8")
            os.replace(str(tmp), str(target))
        except OSError as exc:
            line = f"codex: {target} could not be updated ({exc})"
            out.write(f"{line}\n")
            return [line]
        granted = list(record["set_keys"])
        if record["trusted_checkout"]:
            granted.append(f"trusted {record['trusted_checkout']}")
        actions.append(
            f"codex: enabled unattended mode in {target} ({', '.join(granted)})"
        )
    for conflict in record["conflicts"]:
        actions.append(
            f"codex: left your own setting in place — {conflict}; "
            "Codex will keep asking until you change it"
        )
    for line in actions:
        out.write(f"{line}\n")
    return actions


__all__ = ["configure_codex_unattended_posture"]
