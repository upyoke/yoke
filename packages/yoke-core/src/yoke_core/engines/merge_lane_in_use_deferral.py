"""Name a landed lane another program holds, and who finishes its cleanup.

Windows refuses to rename a folder a shell stands in or a program holds a
file in. The merge itself stands; only the lane's removal waits, so this is a
deferral with its recovery, never a raw WinError.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.public_ref import parse_public_item_ref
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.project_identity_item_ref import item_subject_ref
from yoke_core.tools.session_relay_lane_sweep import SWEEP_INTERVAL_SECONDS


def in_use_deferral(worktree_path: Path, item_id: Any, *, swept: bool) -> str:
    """The merge stands; name the program-held lane and who finishes it.

    The relay's sweep proves a lane landed against origin, so only a checkout
    with a remote is swept; a local-only one names the merge rerun alone.
    """
    ref = item_subject_ref(item_id) if item_id is not None else ""
    rerun = (
        f"rerun `yoke merge item {ref}` from the main checkout"
        if parse_public_item_ref(ref)[0]
        else "rerun the merge from the main checkout"
    )
    finish = (
        f"the relay's lane sweep (every {SWEEP_INTERVAL_SECONDS // 60} minutes) "
        f"then finishes cleanup, or {rerun} to finish now"
        if swept
        else f"then {rerun} to finish cleanup (a project with no remote is not swept)"
    )
    return compose_refusal(
        f"merged; lane cleanup deferred: {worktree_path} in use by another program",
        recovery=(
            "Close the shells and programs using the lane (a Windows shell that "
            f"only changed directory out of it still holds it); {finish}"
        ),
    )


__all__ = ["in_use_deferral"]
