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

from pathlib import Path
from typing import List, Optional

from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.codex_config_posture import (
    changed,
    plan,
    record_written,
)
from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError, mutate


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
    if not target.parent.is_dir():
        return []
    try:
        record = mutate(
            target,
            lambda text, document: plan(text, str(checkout) if checkout else None),
        )
    except CodexHookTrustStoreError as exc:
        return [f"codex: {exc}"]
    actions: List[str] = []
    if changed(record):
        granted = list(record["set_keys"])
        if record["trusted_checkout"]:
            granted.append(f"trusted {record['trusted_checkout']}")
        actions.append(
            f"codex: enabled unattended mode in {target} ({', '.join(granted)})"
        )
        actions.extend(record_written(target, record))
    for conflict in record["conflicts"]:
        actions.append(
            f"codex: left your own setting in place — {conflict}; "
            "Codex asks before commands its rules do not allow"
        )
    return actions


__all__ = ["configure_codex_unattended_posture"]
