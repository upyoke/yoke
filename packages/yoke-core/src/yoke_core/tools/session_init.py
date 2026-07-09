"""Session-init helper for ``/yoke do`` and other loop entrypoints.

Owns the executor / provider / session-id / workspace / lane / model
resolution + ``session-begin`` call that the ``/yoke do`` loop.md
recipe used to compose inline as shell choreography. The skill body
collapses to a single foreground call:

    python3 -m yoke_core.tools.session_init

Stdout: KEY=VALUE lines, one per line, in stable order.

Output keys (always present):
- ``SESSION_ID``       — the YOKE_SESSION_ID (existing env, harness-mapped, or generated)
- ``WORKSPACE``        — git toplevel of the calling cwd
- ``LANE``             — resolved execution lane (advisory; server anchors on session row)
- ``EXECUTOR``         — claude-code | codex | (custom from YOKE_EXECUTOR)
- ``PROVIDER``         — anthropic | openai | (custom from YOKE_PROVIDER)
- ``MODEL``            — resolved from ``harness_sessions.model`` by session id,
                         falling back to ``runtime.harness.hook_helpers_model.detect_model``
- ``MAX_CHAIN_STEPS``  — read from machine config (default 3)

Model resolution is server-owned: SessionStart writes the authoritative
value into ``harness_sessions.model`` (preserving any ``[variant]`` suffix
like ``[1m]``), and ``session_init`` reads it back rather than asking the
LLM agent to substitute a value into the command line.

Exit code 0 on successful resolution + session-begin; non-zero on
non-recoverable failure (no git toplevel, session-begin rejected,
etc.). The session-begin call is idempotent so repeated invocations
across loop iterations are safe.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.tools import python_interpreter_probe
from yoke_core.domain.db_helpers import connect, resolve_db_path
from yoke_harness.hooks.identity import (
    _is_placeholder_model,
    detect_executor,
    detect_model,
    detect_provider,
)


def _resolve_executor() -> str:
    return detect_executor()


def _resolve_provider(executor: str) -> str:
    return detect_provider(executor)


def _resolve_session_id(executor: str) -> str:
    if os.environ.get("YOKE_SESSION_ID"):
        return os.environ["YOKE_SESSION_ID"]
    if os.environ.get("CLAUDE_SESSION_ID"):
        return os.environ["CLAUDE_SESSION_ID"]
    if os.environ.get("CODEX_THREAD_ID"):
        return os.environ["CODEX_THREAD_ID"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{executor}-{ts}-{uuid.uuid4().hex[:6]}"


def _resolve_model(session_id: str, executor: str) -> str:
    """Resolve the canonical model id for *session_id*.

    Reads ``harness_sessions.model`` first (preserves variant suffix
    written by SessionStart) and falls back to
    ``hook_helpers_model.detect_model`` when no row exists or the stored
    value is a placeholder (``unknown`` / ``default`` / ``auto`` / empty).
    """
    try:
        conn = connect(resolve_db_path())
    except Exception:
        return detect_model(executor)
    try:
        row = conn.execute(
            "SELECT model FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if row is not None:
        stored = row["model"] if "model" in row.keys() else row[0]
        if isinstance(stored, str) and not _is_placeholder_model(stored):
            return stored
    return detect_model(executor)


def _resolve_workspace() -> Optional[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _resolve_lane(workspace: str, executor: str) -> str:
    config_path = Path(workspace) / "data" / "config"
    result = subprocess.run(
        [
            sys.executable, "-m", "yoke_core.api.routing_config", "resolve-lane",
            "--config", str(config_path), "--executor", executor,
        ],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return "default"
    lane = result.stdout.strip()
    return lane or "default"


def _read_max_chain_steps(workspace: str) -> str:
    config_path = Path(workspace) / "data" / "config"
    if not config_path.is_file():
        return "3"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("max_chain_steps="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass
    return "3"


def _session_begin(
    session_id: str, executor: str, provider: str, model: str, workspace: str,
) -> int:
    """Idempotent session-begin call. Returns exit code (0 on success)."""
    result = subprocess.run(
        [
            sys.executable, "-m", "yoke_core.api.service_client", "session-begin",
            "--session-id", session_id,
            "--executor", executor,
            "--provider", provider,
            "--model", model,
            "--workspace", workspace,
        ],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="session_init",
        description=(
            "Resolve session identity + harness identity + lane, call "
            "session-begin idempotently, and emit KEY=VALUE lines for the "
            "/yoke do loop to substitute into later Bash calls. Model is "
            "resolved from harness_sessions.model by session id (or via "
            "hook_helpers_model.detect_model when no row exists)."
        ),
    )
    parser.add_argument(
        "--skip-begin", action="store_true",
        help=argparse.SUPPRESS,  # tests / dry-run; skips the session-begin call
    )
    return parser.parse_args(list(argv))


def _emit_interpreter_advisory() -> None:
    """Probe the resolved ``python3`` interpreter and emit an advisory to
    stderr when a confirmed missing dep is detected.

    Stdout MUST stay machine-parseable ``KEY=VALUE`` only — all
    advisory text routes through stderr so ``/yoke do`` and shell
    callers do not misparse the init output. Fail-open on every uncertain
    state per the probe's contract.
    """
    try:
        result = python_interpreter_probe.probe()
    except Exception:
        return
    advisory = python_interpreter_probe.render_advisory(result)
    if advisory:
        print(advisory, file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ns = _parse_args(list(sys.argv[1:] if argv is None else argv))

    _emit_interpreter_advisory()

    executor = _resolve_executor()
    provider = _resolve_provider(executor)
    session_id = _resolve_session_id(executor)
    workspace = _resolve_workspace()
    if not workspace:
        print("Error: not inside a git repository", file=sys.stderr)
        return 1
    lane = _resolve_lane(workspace, executor)
    max_chain_steps = _read_max_chain_steps(workspace)
    model = _resolve_model(session_id, executor)

    if not ns.skip_begin:
        rc = _session_begin(
            session_id=session_id, executor=executor, provider=provider,
            model=model, workspace=workspace,
        )
        if rc != 0:
            print(
                f"Error: session-begin failed with exit {rc}",
                file=sys.stderr,
            )
            return rc

    print(f"SESSION_ID={session_id}")
    print(f"WORKSPACE={workspace}")
    print(f"LANE={lane}")
    print(f"EXECUTOR={executor}")
    print(f"PROVIDER={provider}")
    print(f"MODEL={model}")
    print(f"MAX_CHAIN_STEPS={max_chain_steps}")
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
