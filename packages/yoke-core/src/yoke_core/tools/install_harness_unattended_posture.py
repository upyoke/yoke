"""One install pass that makes every harness on this machine run Yoke unattended.

Yoke's launched workers already bypass approval prompts — the launch plane
passes each harness its own flag. A session a person opens reads the
harness's persisted config instead, and every harness ships defaults that
stop and ask, so a fresh install leaves a stranger approving each ``yoke``
call by hand. This pass closes that gap for each harness actually present,
from the single posture declaration the launch route already reads.

It is deliberately loud. Widening what a harness will run without asking is
the operator's business, so each write is named in the installer's output,
anything the operator has set differently is reported and left alone, and
:mod:`yoke_core.engines.doctor_hc_harness_unattended_posture` reports the
standing posture rather than anyone assuming it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional


def configure_harness_unattended_posture(
    *,
    checkout: Optional[Path] = None,
    stream=None,
) -> List[str]:
    """Apply the posture to every detected harness; return what changed.

    Claude's preference patch is applied by its own module, which predates
    the other two and already owns its refusal and reporting.
    """
    from yoke_core.tools.install_yoke_launcher_claude import (
        configure_claude_app_bypass_permissions,
    )
    from yoke_core.tools.install_yoke_launcher_codex import (
        configure_codex_unattended_posture,
    )
    from yoke_core.tools.install_yoke_launcher_cursor import (
        configure_cursor_unattended_posture,
    )

    out = stream if stream is not None else sys.stdout
    actions: List[str] = []
    # Claude's module prints its own multi-line notice (relaunch instructions
    # the other two have no equivalent of), so it reports and this adds the
    # one-line summary; the other two report only, and are printed here.
    if configure_claude_app_bypass_permissions(stream=out):
        actions.append("claude-code: enabled bypass permissions in Claude.app")
    reported = list(
        configure_codex_unattended_posture(checkout=checkout)
    ) + list(configure_cursor_unattended_posture())
    for line in reported:
        out.write(f"{line}\n")
    actions.extend(reported)
    if not actions:
        out.write(
            "Harness approval posture: no change needed "
            "(every detected harness already runs yoke unattended).\n"
        )
    return actions


__all__ = ["configure_harness_unattended_posture"]
