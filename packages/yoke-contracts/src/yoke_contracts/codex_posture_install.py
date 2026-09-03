"""Write the unattended posture into Codex's own ``config.toml``.

The TOML surgery lives in
:mod:`yoke_contracts.codex_config_posture`; this module is the
IO around it. It reports and never prints — the one pass that drives all
three harnesses owns the output, so no line can be reported twice. Codex reads no project-local config, so the
machine file is the only place its posture can live — including the
directory-trust entry for the checkout being installed, without which Codex
asks about the folder itself before it asks about anything in it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.codex_config_posture import (
    CodexConfigUnreadable,
    changed,
    plan,
    read_config_text,
)


def configure_codex_unattended_posture(
    *,
    checkout: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> List[str]:
    """Set Codex's approval, sandbox, and trust keys; return what it reports.

    An empty list means nothing to say: Codex is absent, or already
    unattended.
    """
    target = config_path if config_path is not None else codex_config_path()
    text = read_config_text(target)
    if text is None:
        return []
    try:
        updated, record = plan(text, str(checkout) if checkout else None)
    except CodexConfigUnreadable as exc:
        return [
            f"codex: {target} is not valid TOML ({exc}); Codex reads no "
            "posture from it and will keep asking. Repair the file, then "
            "rerun the installer."
        ]
    actions: List[str] = []
    if changed(record):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".yoke-tmp")
        try:
            tmp.write_text(updated, encoding="utf-8")
            os.replace(str(tmp), str(target))
        except OSError as exc:
            return [f"codex: {target} could not be updated ({exc})"]
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
    return actions


__all__ = ["configure_codex_unattended_posture"]
