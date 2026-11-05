"""Command-line interface for merge lock diagnostics."""

import sys
from typing import Optional

from yoke_core.domain.merge_lock import LockHandle, acquire, check, force_clear, release


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: merge_lock.py <check|acquire|release|force-clear> [args...]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]

    if cmd == "check":
        msg = check()
        if msg:
            print(msg, file=sys.stderr)
            return 1
        return 0

    elif cmd == "acquire":
        if len(args) < 2:
            print("Usage: merge_lock.py acquire <branch> [epic_ref]", file=sys.stderr)
            return 2
        branch = args[1]
        epic_ref = args[2] if len(args) > 2 else None
        handle = acquire(branch, epic_ref)
        # Output session_id so the caller can pass it to release
        print(f"{handle.session_id}")
        return 0

    elif cmd == "release":
        if len(args) < 3:
            print("Usage: merge_lock.py release <session_id> <branch>", file=sys.stderr)
            return 2
        handle = LockHandle(session_id=args[1], branch=args[2])
        release(handle)
        return 0

    elif cmd == "force-clear":
        force_clear()
        return 0

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2
