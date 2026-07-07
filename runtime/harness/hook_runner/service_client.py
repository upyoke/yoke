"""Service-client subprocess driver helpers + transcript-based model refresh.

Owns repo-root resolution for hook CLI entrypoints, the
``service_client.py`` path lookup, the ``register_session`` driver, and
the post-turn ``refresh_session_model_if_placeholder`` upgrade path.
Re-exported via ``runtime.harness.hook_runner.telemetry`` so post-cutover
callers route through one canonical telemetry surface.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import subprocess
from pathlib import Path
from typing import Iterator, Optional

_RETIRED_BACKEND_ENV = "YOKE_" + "BACKEND"


def resolve_repo_root() -> str:
    """Resolve the code root for hook CLI entrypoints."""
    code_root = os.environ.get("YOKE_CODE_ROOT", "")
    if code_root and os.path.isdir(os.path.join(code_root, "runtime", "api")):
        return code_root

    env_root = os.environ.get("YOKE_REPO_ROOT", "")
    if env_root and os.path.isdir(os.path.join(env_root, "runtime", "api")):
        return env_root

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        try:
            result = subprocess.run(
                ["git", "-C", project_dir, "worktree", "list", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("worktree "):
                        candidate = line[len("worktree "):]
                        if os.path.isdir(os.path.join(candidate, "runtime", "api")):
                            return candidate
                        break
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        if os.path.isdir(os.path.join(project_dir, "runtime", "api")):
            return project_dir

    from yoke_core.api.repo_root import find_repo_root

    return str(find_repo_root(Path(__file__)))


def session_service_client_path() -> str:
    """Return the service_client.py path for hook/session commands."""
    return os.path.join(resolve_repo_root(), "runtime", "api", "service_client.py")


def _connected_env_allowed_in_this_process() -> bool:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        or "pytest" in __import__("sys").modules
    ):
        from yoke_core.domain import yoke_connected_env

        return os.environ.get(yoke_connected_env.PYTEST_ENABLE_ENV) == "1"
    return True


def target_authority_env(root: str) -> dict[str, str]:
    """Return env overrides that anchor hook children to the target workspace."""
    overrides: dict[str, str] = {}
    if root:
        overrides["YOKE_ROOT"] = root
    if not root or not _connected_env_allowed_in_this_process():
        return overrides
    try:
        from yoke_core.domain import db_backend, machine_config, yoke_connected_env

        binding = yoke_connected_env.find_binding(Path(root))
        if binding:
            overrides[machine_config.CONFIG_FILE_ENV] = str(binding)
        overrides.update(
            yoke_connected_env.process_env_overrides(
                dsn_env=db_backend.PG_DSN_ENV,
                dsn_file_env=db_backend.PG_DSN_FILE_ENV,
                start=Path(root),
            )
        )
    except Exception:
        pass
    return overrides


def _service_client_repo_root(service_client_path: str) -> str:
    try:
        return str(Path(service_client_path).resolve().parents[2])
    except (IndexError, OSError):
        return ""


def target_process_env(root: str, code_root: str = "") -> dict[str, str]:
    """Return a subprocess env pinned to the target repo and DB authority."""
    env = os.environ.copy()
    env.pop(_RETIRED_BACKEND_ENV, None)
    env.update(target_authority_env(root))
    pythonpath_roots: list[str] = []
    for candidate in (code_root, root):
        if candidate and candidate not in pythonpath_roots:
            pythonpath_roots.append(candidate)
    if pythonpath_roots:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            [*pythonpath_roots, *([existing] if existing else [])]
        )
    return env


@contextmanager
def target_process_environment(root: str) -> Iterator[None]:
    """Temporarily apply target authority env to in-process hook DB calls."""
    updates = target_authority_env(root)
    old = {key: os.environ.get(key) for key in (*updates, _RETIRED_BACKEND_ENV)}
    os.environ.pop(_RETIRED_BACKEND_ENV, None)
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _target_cwd(root: str, service_client_path: str = "") -> Optional[str]:
    if root and os.path.isdir(root):
        return root
    if service_client_path:
        try:
            return str(Path(service_client_path).resolve().parents[2])
        except IndexError:
            return None
    return None


def register_session(
    service_client_path: str,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    entrypoint: Optional[str] = None,
    project_id: Optional[int] = None,
) -> Optional[str]:
    """Register/touch a session via service_client.py session-begin.

    Returns None on success, or an error message string on failure.

    ``entrypoint``, when provided, identifies the harness sub-surface
    (e.g. ``claude-desktop``, ``claude-vscode-extension``, ``cli``) and
    is recorded in the HarnessSessionStarted event context for telemetry.
    """
    if not os.path.isfile(service_client_path):
        return "service_client.py not found"

    cmd = [
        "python3",
        service_client_path,
        "session-begin",
        "--session-id",
        session_id,
        "--executor",
        executor,
        "--provider",
        provider,
        "--model",
        model,
        "--workspace",
        workspace,
    ]
    if project_id is not None:
        cmd.extend(["--project-id", str(project_id)])
    if entrypoint:
        cmd.extend(["--entrypoint", entrypoint])

    try:
        cwd = _target_cwd(workspace, service_client_path)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=target_process_env(
                cwd or workspace,
                _service_client_repo_root(service_client_path),
            ),
            timeout=10,
        )
        if result.returncode != 0:
            return result.stderr.strip() or result.stdout.strip() or "unknown error"
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return str(e)


def touch_session(service_client_path: str, root: str, session_id: str) -> int:
    """Heartbeat an active session through the same authority-pinned child."""
    if not os.path.isfile(service_client_path):
        return 1
    try:
        cwd = _target_cwd(root, service_client_path)
        result = subprocess.run(
            ["python3", service_client_path, "session-touch", "--session-id", session_id],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=target_process_env(
                cwd or root,
                _service_client_repo_root(service_client_path),
            ),
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 1
    return result.returncode


def refresh_session_model_if_placeholder(
    db_path: str,
    session_id: str,
    transcript_path: str,
    *,
    hook_source: str = "",
) -> bool:
    """Upgrade a placeholder ``harness_sessions.model`` using the transcript.

    Intended for hooks that fire after the LLM has begun generating (and
    so the transcript's assistant-message ``model`` field is now present).
    Safe to call from every hook — no-ops when:
      * the stored model is already real, or
      * the transcript yields no non-placeholder model, or
      * the DB / schema / session row isn't available.

    Never downgrades a real stored model to a placeholder.

    Emits a ``HarnessSessionModelRefreshed`` event when an upgrade fires,
    so we can trace which hook surface did the upgrade and when.

    Returns True when an UPDATE fired, False otherwise.
    """
    if not session_id or not transcript_path:
        return False
    from runtime.harness.hook_helpers import (
        _is_placeholder_model,
        _read_model_from_transcript,
    )

    transcript_model = _read_model_from_transcript(transcript_path)
    if not transcript_model or _is_placeholder_model(transcript_model):
        return False

    try:
        from yoke_core.domain import db_backend

        conn = db_backend.connect(db_path or None, busy_timeout_ms=2000)
    except Exception:
        return False
    try:
        row = conn.execute(
            "SELECT model FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        stored = row[0] or ""
        if not _is_placeholder_model(stored):
            return False
        conn.execute(
            "UPDATE harness_sessions SET model = %s WHERE session_id = %s",
            (transcript_model, session_id),
        )
        conn.commit()
    except Exception:
        return False
    finally:
        conn.close()

    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _native_emit(
            "HarnessSessionModelRefreshed",
            event_kind="system",
            event_type="session_lifecycle",
            source_type="hook",
            severity="INFO",
            outcome="completed",
            session_id=session_id,
            project="yoke",
            context={
                "previous_model": stored,
                "refreshed_model": transcript_model,
                "hook_source": hook_source or "unknown",
            },
        )
    except Exception:
        pass
    return True


__all__ = [
    "refresh_session_model_if_placeholder",
    "register_session",
    "resolve_repo_root",
    "session_service_client_path",
    "target_authority_env",
    "target_process_env",
    "target_process_environment",
    "touch_session",
]
