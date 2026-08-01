"""Pre-dispatch check that a run will not regress a project's version pin.

The comparison runs here rather than server-side because both sides of it
live in the caller's checkout: the candidate ref and the environment's pin
branch are refs in the same repository, and the server never sees that
repository. The guard is advisory in the same sense the PreToolUse lints
are — it refuses the ordinary path and names the override.
"""

from __future__ import annotations

import argparse
from typing import Optional


def pin_regression_error(parsed: argparse.Namespace) -> Optional[str]:
    """Message describing a refused pin rollback, or None to proceed."""
    if getattr(parsed, "allow_pin_regression", False):
        return None
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_pin_regression import (
        PinRegressionError,
        assert_no_pin_regression,
    )
    from yoke_core.domain.project_identity import resolve_project

    conn = connect()
    try:
        project_id = resolve_project(conn, parsed.project)
        if isinstance(project_id, tuple):
            project_id = project_id[0]
        target_env = parsed.target_env
        if not target_env:
            row = conn.execute(
                "SELECT target_env FROM deployment_flows WHERE id=%s",
                (parsed.flow,),
            ).fetchone()
            if row is not None:
                target_env = row[0] if not isinstance(row, dict) else row.get(
                    "target_env"
                )
        try:
            assert_no_pin_regression(
                conn,
                project_id=int(project_id),
                repo_path=parsed.project_repo_path,
                source_ref=parsed.source_ref,
                target_env=target_env,
            )
        except PinRegressionError as exc:
            return str(exc)
    except Exception:
        # A guard that cannot read its own inputs must not block a deploy;
        # the declaration is optional and any resolution failure here is a
        # missing capability or an unreachable control plane, not evidence
        # of a rollback.
        return None
    finally:
        conn.close()
    return None


__all__ = ["pin_regression_error"]
