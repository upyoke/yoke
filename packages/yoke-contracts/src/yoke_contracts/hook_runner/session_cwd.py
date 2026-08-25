"""Client/authority contract for session-cwd scratch-root evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


CLIENT_SCRATCH_ROOT_KEY = "_yoke_client_scratch_root"
CLIENT_SCRATCH_ROOT_SCHEMA = 1
CLIENT_CLAUDE_JOB_TMP_KEY = "_yoke_client_claude_job_tmp"
CLIENT_CLAUDE_JOB_TMP_SCHEMA = 1


def _valid_root(root: object) -> str:
    value = root.strip() if isinstance(root, str) else ""
    path = Path(value).expanduser()
    if not value or not path.is_absolute() or path == Path(path.anchor):
        return ""
    return value


def client_scratch_root_fact(root: str) -> dict[str, object]:
    """Build the relayed fact naming the client machine's scratch root."""

    value = _valid_root(root)
    if not value:
        return {}
    return {
        CLIENT_SCRATCH_ROOT_KEY: {
            "schema": CLIENT_SCRATCH_ROOT_SCHEMA,
            "root": value,
        }
    }


def client_scratch_root(payload: Mapping[str, Any]) -> str:
    """Return a schema-validated client scratch root from a hook payload."""

    raw = payload.get(CLIENT_SCRATCH_ROOT_KEY)
    if not isinstance(raw, Mapping):
        return ""
    if raw.get("schema") != CLIENT_SCRATCH_ROOT_SCHEMA:
        return ""
    return _valid_root(raw.get("root"))


def _valid_claude_job_tmp(root: object) -> str:
    value = _valid_root(root)
    if not value:
        return ""
    path = Path(value).expanduser().resolve()
    if (
        path.name != "tmp"
        or path.parent.parent.name != "jobs"
        or path.parent.parent.parent.name != ".claude"
    ):
        return ""
    return str(path)


def claude_job_tmp_root(job_dir: object) -> str:
    """Resolve the harness-owned ``$CLAUDE_JOB_DIR/tmp`` subtree."""
    value = job_dir.strip() if isinstance(job_dir, str) else ""
    if not value:
        return ""
    return _valid_claude_job_tmp(str(Path(value).expanduser() / "tmp"))


def client_claude_job_tmp_fact(job_dir: str) -> dict[str, object]:
    """Build relayed evidence for one Claude background-job temp root."""
    root = claude_job_tmp_root(job_dir)
    if not root:
        return {}
    return {
        CLIENT_CLAUDE_JOB_TMP_KEY: {
            "schema": CLIENT_CLAUDE_JOB_TMP_SCHEMA,
            "root": root,
        }
    }


def client_claude_job_tmp(
    payload: Mapping[str, Any], *, job_dir: str = "",
) -> str:
    """Return validated relayed evidence, or a local job-dir fallback."""
    raw = payload.get(CLIENT_CLAUDE_JOB_TMP_KEY)
    if (
        isinstance(raw, Mapping)
        and raw.get("schema") == CLIENT_CLAUDE_JOB_TMP_SCHEMA
    ):
        root = _valid_claude_job_tmp(raw.get("root"))
        if root:
            return root
    return claude_job_tmp_root(job_dir)


__all__ = [
    "CLIENT_CLAUDE_JOB_TMP_KEY",
    "CLIENT_CLAUDE_JOB_TMP_SCHEMA",
    "CLIENT_SCRATCH_ROOT_KEY",
    "CLIENT_SCRATCH_ROOT_SCHEMA",
    "claude_job_tmp_root",
    "client_claude_job_tmp",
    "client_claude_job_tmp_fact",
    "client_scratch_root",
    "client_scratch_root_fact",
]
