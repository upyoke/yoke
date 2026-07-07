"""Subprocess policy launch helpers for the shared hook runner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from runtime.harness.hook_runner.types import HookContext


def _target_root(context: HookContext) -> str:
    root = context.target_root or context.cwd or ""
    return root if root and os.path.isdir(root) else ""


def _target_env(root: str) -> dict[str, str]:
    env = os.environ.copy()
    code_root = str(Path(__file__).resolve().parents[3])
    try:
        from runtime.harness.hook_runner.service_client import target_authority_env

        if root:
            env.update(target_authority_env(root))
    except Exception:
        pass
    if root:
        env.setdefault("YOKE_ROOT", root)
        env.setdefault("YOKE_REPO_ROOT", root)
    env.setdefault("YOKE_CODE_ROOT", code_root)
    paths = [code_root]
    if root and root != code_root:
        paths.append(root)
    existing = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    for path in existing:
        if path not in paths:
            paths.append(path)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _observe_args(module_id: str, context: HookContext, root: str) -> list[str]:
    args = [sys.executable, "-m", module_id]
    if module_id != "yoke_core.domain.observe":
        return args
    args.extend(["--hook-event", context.event_name])
    if context.session_id:
        args.extend(["--session-id", context.session_id])
    tool_use_id = context.payload.get("tool_use_id")
    if tool_use_id:
        args.extend(["--tool-use-id", str(tool_use_id)])
    if root:
        args.extend(["--project-dir", root])
    return args


def run_subprocess_policy(
    module_id: str,
    *,
    context: HookContext,
    stdin_data: str,
    timeout_ms: int,
) -> tuple[Optional[str], str]:
    """Run ``module_id`` as ``python -m`` with target-root import authority."""
    root = _target_root(context)
    try:
        completed = subprocess.run(  # noqa: S603 - module id comes from registry
            _observe_args(module_id, context, root),
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
            cwd=root or None,
            env=_target_env(root),
        )
    except subprocess.TimeoutExpired:
        return f"timeout_{timeout_ms}ms", ""
    except UnicodeDecodeError:
        return "decode_error", ""
    except Exception as exc:  # noqa: BLE001 - fail open, never crash chain
        return f"exception_{type(exc).__name__}", ""

    captured = completed.stdout or ""
    if completed.returncode != 0:
        return f"exit_{completed.returncode}", captured
    return None, captured


__all__ = ["run_subprocess_policy"]
