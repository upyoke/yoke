"""CLI mode parsing for ``python3 -m yoke_core.domain.epic_task_sync``.

The parent ``epic_task_sync`` module owns the patchable module-level imports,
shared sync utilities, USAGE constants, and the wrapper functions
(`sync_epic_tasks`, `sync_task_label`, etc.). This sibling owns mode
dispatch and arg parsing so the parent stays at or below the file-line
budget while preserving the module operator entrypoint.

``run`` imports the parent module object inside the call body so existing
tests that patch ``yoke_core.domain.epic_task_sync.sync_epic_tasks`` (or
its peers) continue to intercept behavior through the wrapper functions.
"""

from __future__ import annotations

import sys
from typing import Optional


def run(argv: Optional[list[str]] = None) -> int:
    # Imported inside the function so the parent module's module-level
    # attributes are the patch surface tests use. Importing at module scope
    # would freeze references at import time and bypass patching.
    import yoke_core.domain.epic_task_sync as parent

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "Usage: epic_task_sync.py <sync|label|body|progress|backfill-titles|backfill-labels> ...",
            file=sys.stderr,
        )
        return 2

    mode = args.pop(0)

    if mode == "sync":
        if not args:
            print(parent.SYNC_USAGE, file=sys.stderr)
            return 1
        epic_ref = args[0]
        epic_dir = args[1] if len(args) > 1 else ""
        return parent.sync_epic_tasks(epic_ref, epic_dir)

    if mode == "label":
        if len(args) != 3:
            print(parent.LABEL_USAGE, file=sys.stderr)
            return 0
        epic_id, task_num, new_status = args
        try:
            task_num_int = int(task_num)
        except ValueError:
            print(parent.LABEL_USAGE, file=sys.stderr)
            return 0
        return parent.sync_task_label(epic_id, task_num_int, new_status)

    if mode == "body":
        if len(args) != 2:
            print(parent.BODY_USAGE, file=sys.stderr)
            return 2
        epic_id, task_num = args
        try:
            task_num_int = int(task_num)
        except ValueError:
            print(parent.BODY_USAGE, file=sys.stderr)
            return 2
        return parent.sync_task_body(epic_id, task_num_int)

    if mode == "progress":
        if len(args) not in {1, 2}:
            print(parent.PROGRESS_USAGE, file=sys.stderr)
            return 1
        return parent.sync_progress_notes(args[0], args[1] if len(args) == 2 else None)

    if mode == "backfill-titles":
        if len(args) != 1:
            print(parent.BACKFILL_TITLES_USAGE, file=sys.stderr)
            return 1
        return parent.backfill_task_titles(args[0])

    if mode == "backfill-labels":
        if len(args) != 1:
            print(parent.BACKFILL_LABELS_USAGE, file=sys.stderr)
            return 1
        return parent.backfill_task_labels(args[0])

    print(
        "Usage: epic_task_sync.py <sync|label|body|progress|backfill-titles|backfill-labels> ...",
        file=sys.stderr,
    )
    return 2
