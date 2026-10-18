"""Resolve and run Postgres executables detached from the calling terminal."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from yoke_contracts import terminal_detached_process


def executable(bin_dir: Optional[Path], name: str) -> str:
    """Resolve one Postgres executable from an optional pinned bin dir.

    ``None`` falls back to ``PATH`` (bare name); a directory pins the
    tool. One resolution rule shared by the cluster lifecycle (via
    :func:`yoke_core.domain.postgres_cluster.binary`) and standalone tool
    invocations such as the universe-export ``pg_dump``.
    """
    if bin_dir is None:
        return name
    return str(bin_dir / name)


def _env() -> dict:
    # LC_ALL=C avoids the macOS "postmaster became multithreaded during
    # startup" FATAL that fires when the cluster inherits an unset/invalid
    # locale.
    return {**os.environ, "LC_ALL": "C", "LANG": "C"}


def _run(argv, *, env: dict | None = None, **kw) -> subprocess.CompletedProcess:
    # initdb, pg_ctl and psql run while setup's wizard may own the terminal;
    # detached, they can neither read it nor take its foreground, and the
    # server pg_ctl starts is not tied to the terminal's session.
    return terminal_detached_process.run(
        argv,
        env=env if env is not None else _env(),
        text=True,
        capture_output=True,
        **kw,
    )
