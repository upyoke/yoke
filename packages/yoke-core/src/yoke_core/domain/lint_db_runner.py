"""Runner/executor for the neutral Bash DB-command policy engine.

``lint-sqlite-cmd`` is retained as the legacy stable telemetry/check id; this
module is the implementation-facing name. It executes
:data:`yoke_core.domain.lint_db_rules.HOOK_POLICY_SOURCE` against a
PreToolUse payload, capturing stdin/stdout so the hook can be driven from tests
or called programmatically without a subprocess.
"""

from __future__ import annotations

import contextlib
import io
import sys

from yoke_core.domain.lint_db_rules import HOOK_POLICY_SOURCE


def run_hook(payload: str, yoke_db: str = "") -> str:
    """Run the DB-command policy against a PreToolUse payload.

    Returns the JSON denial/warning payload emitted by the historical inline
    policy engine, or an empty string when the command is allowed.
    """
    import os

    previous_db = os.environ.get("YOKE_DB")
    if yoke_db:
        os.environ["YOKE_DB"] = yoke_db
    elif previous_db is None:
        os.environ.pop("YOKE_DB", None)
    else:
        os.environ.pop("YOKE_DB", None)

    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    original_stdin = sys.stdin
    try:
        sys.stdin = stdin
        with contextlib.redirect_stdout(stdout):
            try:
                exec(HOOK_POLICY_SOURCE, {"__name__": "__lint_db_cmd__"})
            except SystemExit:
                pass
    finally:
        sys.stdin = original_stdin
        if previous_db is None:
            os.environ.pop("YOKE_DB", None)
        else:
            os.environ["YOKE_DB"] = previous_db

    return stdout.getvalue().rstrip("\n")


__all__ = ("run_hook",)
