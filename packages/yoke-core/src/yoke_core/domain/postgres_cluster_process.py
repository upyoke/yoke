"""Resolve and run Postgres executables detached from the calling terminal."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from yoke_contracts import terminal_detached_process

_WINDOWS = os.name == "nt"


def executable(bin_dir: Optional[Path], name: str) -> str:
    """Resolve one Postgres executable from an optional pinned bin dir.

    ``None`` falls back to ``PATH`` (bare name); a directory pins the
    tool. One resolution rule shared by the cluster lifecycle (via
    :func:`yoke_core.domain.postgres_cluster.binary`) and standalone tool
    invocations such as the universe-export ``pg_dump``.
    """
    if _WINDOWS:
        name += ".exe"
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
    selected_env = dict(env if env is not None else _env())
    if _WINDOWS:
        bin_dir = Path(argv[0]).parent
        selected_env["PATH"] = os.pathsep.join([
            str(bin_dir), str(bin_dir / "DLLs"),
            selected_env.get("PATH", ""),
        ])
    # A postmaster must never keep a captured pipe open after pg_ctl exits.
    # Real files bound the wait to the helper, even when grandchildren inherit.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out, \
            tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err:
        try:
            result = terminal_detached_process.run(
                argv, env=selected_env, text=True, stdout=out, stderr=err,
                timeout=kw.pop("timeout", 90), **kw,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                argv, 1, "", "postgres_process_timeout: helper did not exit within "
                "its deadline; inspect server.log and retry the local Postgres command.",
            )
        out.seek(0)
        err.seek(0)
        result.stdout, result.stderr = out.read(), err.read()
    if result.returncode == 0xC0000135:
        result.stderr += (
            "embedded_postgres_dll_missing: Windows could not load a PostgreSQL "
            "runtime DLL; run `yoke local-postgres start` to refetch the pinned "
            "engine, then retry."
        )
    return result
