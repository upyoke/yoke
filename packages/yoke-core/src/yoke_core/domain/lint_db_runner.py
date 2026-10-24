"""Runner for the neutral Bash DB-command policy engine.

``lint-sqlite-cmd`` is retained as the default DB-command compatibility id;
condition-specific denials may carry their own registered id. This module executes
:data:`yoke_core.domain.lint_db_rules.HOOK_POLICY_SOURCE` against a
PreToolUse payload, capturing stdin/stdout so the hook can be driven from tests
or called programmatically without a subprocess.
"""

from __future__ import annotations

import io
import sys

from yoke_core.domain.lint_db_rules import HOOK_POLICY_SOURCE
from yoke_core.hooks.types import HookDecision, Next, Outcome


def run_hook(payload: str, yoke_db: str = "") -> HookDecision:
    """Run the DB-command policy against a PreToolUse payload.

    Returns a plain decision from the rule fragments, or NOOP when allowed.
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
    namespace = {
        "__name__": "__lint_db_cmd__",
        "HookDecision": HookDecision,
        "Outcome": Outcome,
        "Next": Next,
    }
    original_stdin = sys.stdin
    try:
        sys.stdin = stdin
        try:
            exec(HOOK_POLICY_SOURCE, namespace)
        except SystemExit:
            pass
    finally:
        sys.stdin = original_stdin
        if previous_db is None:
            os.environ.pop("YOKE_DB", None)
        else:
            os.environ["YOKE_DB"] = previous_db

    return namespace.get("result", HookDecision(outcome=Outcome.NOOP))


__all__ = ("run_hook",)
