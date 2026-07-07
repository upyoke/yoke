"""Session-ID auto-resolution and CLI argument helpers.

Owns the CLI-side session-id chokepoint (explicit operator-debug
override first, then the canonical ambient chain owned by
:mod:`yoke_core.domain.session_ambient_identity`), plus the small
parsers used by the service_client commands: ``PREFIX-N`` → internal
``items.id`` resolution (via the shared per-project parser), the
shell-wrapper output mode flag, and the YOKE_ROOT path normalizer.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.domain.session_ambient_identity import (
    AMBIENT_RESOLUTION_FAILED,
    resolve_ambient_session_id,
)
from yoke_core.api.service_client_shared_io import _repo_root


# Single denial line for session-requiring CLI commands: the explicit flag
# is the operator-debug override; absence of any ambient identity is an
# infrastructure-bug signal, never a prompt to export env vars.
SESSION_REQUIRED_ERROR = f"Error: {AMBIENT_RESOLUTION_FAILED}"


def _resolve_session_id(explicit: str | None) -> str | None:
    """Resolve a session ID: explicit override, then the ambient chain.

    When *explicit* is a non-empty string it is returned as-is — the
    flagged operator-debug override. Otherwise the canonical ambient
    chain resolves: ``YOKE_SESSION_ID`` → ``CLAUDE_SESSION_ID`` →
    ``CODEX_THREAD_ID`` → the hook-written process-anchor registry
    (ancestry walk). Returns ``None`` if no value is found anywhere.
    """
    if explicit:
        return explicit
    return resolve_ambient_session_id()


def current_session_id() -> str:
    """Resolve the active harness session id from the ambient chain.

    Public wrapper around the ambient probe — the canonical
    ``session_identity`` cross-cutting entrypoint surface. Returns
    ``""`` when no ambient identity resolves so callers can treat the
    empty string as "no session context" and skip session-scoped work.
    """
    return _resolve_session_id(None) or ""


def _parse_item_id_arg(raw: str) -> int:
    """Resolve an item-id argument to the internal ``items.id``.

    Accepts a bare internal id, ``PREFIX-N`` (resolved per-project via the
    project's ``public_item_prefix`` + ``project_sequence``), or a project-local
    bare sequence when project context is known. Delegates to the shared
    ``yok_n_parser`` so project-local prefixes resolve correctly and a
    ``PREFIX-N`` ref maps to its project sequence rather than being treated as
    the bare global id — which only coincided while ``project_sequence`` was
    backfilled equal to ``items.id``.
    """
    from yoke_core.domain.yok_n_parser import parse_item_id

    return parse_item_id(raw, allow_bare_internal=True)


def _shell_wrapper_mode() -> bool:
    """Return True when the caller wants shell-friendly log/error output."""
    return os.environ.get("YOKE_SERVICE_CLIENT_SHELL", "0") == "1"


def _normalize_yoke_root(raw_root: str) -> Path:
    """Normalize a repo-or-yoke root path to the concrete data/ dir."""
    try:
        from yoke_core.domain.worktree import resolve_yoke_root

        return Path(resolve_yoke_root(yoke_root_env=raw_root)).resolve()
    except (ImportError, RuntimeError):
        candidate = Path(raw_root).resolve()
        if (candidate / "config").is_file():
            return candidate
        nested = candidate / "data"
        if (nested / "config").is_file():
            return nested
        return candidate


def _isolated_test_mutation_error() -> str | None:
    """Return an error when YOKE_CLAIM_BYPASS=test targets the canonical DB."""
    bypass = os.environ.get("YOKE_CLAIM_BYPASS", "")
    if bypass != "test" and not bypass.startswith("test:"):
        return None

    if os.environ.get("YOKE_ROOT_EXPLICIT", "0") != "1":
        return (
            "YOKE_CLAIM_BYPASS=test requires explicit isolated YOKE_ROOT; "
            "refusing to mutate the canonical Yoke DB"
        )

    env_root = os.environ.get("YOKE_ROOT", "").strip()
    if not env_root:
        return (
            "YOKE_CLAIM_BYPASS=test requires explicit isolated YOKE_ROOT; "
            "refusing to mutate the canonical Yoke DB"
        )

    canonical_root = (Path(_repo_root) / "data").resolve()
    target_root = _normalize_yoke_root(env_root)
    if target_root == canonical_root:
        return (
            "YOKE_CLAIM_BYPASS=test requires explicit isolated YOKE_ROOT; "
            "refusing to mutate the canonical Yoke DB"
        )
    return None
