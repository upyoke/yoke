from __future__ import annotations

import tempfile
from pathlib import Path


def _stub_ctx(*, item_id: str = "1385", branch: str = "YOK-1385"):
    from yoke_core.engines.merge_worktree import MergeArgs, MergeContext

    args = MergeArgs(branch=branch, target="main")
    ctx = MergeContext(args=args)
    ctx.repo_root = str(Path(tempfile.gettempdir()))
    ctx.item_id = item_id
    return ctx
