"""Executor / provider / entrypoint detection for hook owners.

Owns the surface-specific composition rules
(``claude-desktop``/``codex-vscode``/etc.), the ``is_codex`` /
``is_claude`` family predicates, and the resolution chains that
hooks and the service client lean on for telemetry attribution.
"""

from __future__ import annotations

import os
import re
from typing import Optional


# Coarse executor families. Surface-specific values are formed as
# ``{family}-{surface}`` (e.g. ``claude-desktop``, ``codex-vscode``); the
# coarse family value is used as a fallback when no surface signal is
# available.
_CLAUDE_LEGACY = "claude"
_CLAUDE_COARSE = "claude-code"
_CODEX_COARSE = "codex"


def is_codex(executor: Optional[str]) -> bool:
    """True for the coarse Codex executor and any ``codex-*`` surface."""
    if not executor:
        return False
    e = executor.strip().lower()
    return e == _CODEX_COARSE or e.startswith("codex-")


def is_claude(executor: Optional[str]) -> bool:
    """True for Claude's legacy alias, coarse id, and any ``claude-*`` surface."""
    if not executor:
        return False
    e = executor.strip().lower()
    return e in {_CLAUDE_LEGACY, _CLAUDE_COARSE} or e.startswith("claude-")


def canonical_harness_id(executor: Optional[str]) -> str:
    """Map a coarse or surface-specific executor value to the canonical ``harness_id`` enum.

    Returns exactly ``claude-code`` or ``codex``. Raises :class:`ValueError`
    for empty / ``None`` / unknown inputs — silent coercion of an unknown
    executor into a canonical value would poison attribution downstream.
    Callers that legitimately tolerate unknowns (for example the historical-
    rows migration) catch the exception and route the row through the
    explicit refuse-or-report policy instead of substituting a guess.
    """
    if not executor or not executor.strip():
        raise ValueError("canonical_harness_id requires a non-empty executor")
    e = executor.strip().lower()
    if is_codex(e):
        return _CODEX_COARSE
    if is_claude(e):
        return _CLAUDE_COARSE
    raise ValueError(f"unknown harness executor: {executor!r}")


def _normalize_surface_token(value: str) -> str:
    """Lowercase a raw entrypoint string and squash non-alnum to single dashes."""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _compose_executor(family: str, coarse: str, raw_entrypoint: Optional[str]) -> str:
    """Compose ``{family}-{surface}`` from a raw entrypoint string.

    - Empty/None raw entrypoint -> coarse fallback (``claude-code``/``codex``).
    - Entrypoint already starting with the family prefix or equal to the coarse
      value is kept verbatim after normalization (e.g. ``codex_cli`` ->
      ``codex-cli``).
    - Otherwise prefixed with ``{family}-``.
    """
    if not raw_entrypoint:
        return coarse
    normalized = _normalize_surface_token(raw_entrypoint)
    if not normalized:
        return coarse
    if normalized == coarse or normalized.startswith(f"{family}-"):
        return normalized
    return f"{family}-{normalized}"


def compose_executor_from_entrypoint(
    executor: Optional[str],
    entrypoint: Optional[str],
) -> str:
    """Return the specific executor value implied by ``executor`` + ``entrypoint``.

    This is the write-path companion to :func:`detect_executor`.  Hook bridges
    sometimes invoke ``session-begin`` with a coarse family executor plus a
    specific entrypoint (`codex` + `codex-desktop`).  The stored
    ``harness_sessions.executor`` value should still be specific so config lane
    resolution and board rendering see the real surface.

    Unknown/non-family executors are returned verbatim.
    """
    value = (executor or "").strip()
    if is_codex(value):
        return _compose_executor("codex", _CODEX_COARSE, entrypoint)
    if is_claude(value):
        return _compose_executor("claude", _CLAUDE_COARSE, entrypoint)
    return value


def detect_executor() -> str:
    """Detect the current harness executor with surface specificity.

    Resolution order:
      1. ``YOKE_EXECUTOR`` — explicit override; stored verbatim.
      2. Codex family (``CODEX_THREAD_ID`` set) -> ``codex-{surface}`` from the
         full Codex entrypoint resolver (env -> transcript -> cache). Coarse
         ``codex`` when every source misses.
      3. Claude family -> ``claude-{surface}`` from ``CLAUDE_CODE_ENTRYPOINT``
         (observed values: ``claude-desktop``, ``claude-vscode``).  Coarse
         ``claude-code`` when the env var is unset.

    The composed value is always ``coarse`` or ``{family}-{surface}`` so
    downstream callers can prefix-match on family and the lane resolver can key
    off either coarse or specific values.
    """
    if os.environ.get("YOKE_EXECUTOR"):
        return os.environ["YOKE_EXECUTOR"]
    if os.environ.get("CODEX_THREAD_ID"):
        from runtime.harness.codex.codex_model import resolve_entrypoint

        return _compose_executor(_CODEX_COARSE, _CODEX_COARSE, resolve_entrypoint())
    return _compose_executor("claude", _CLAUDE_COARSE, os.environ.get("CLAUDE_CODE_ENTRYPOINT"))


def detect_provider(executor: Optional[str] = None) -> str:
    """Detect the inference provider."""
    if os.environ.get("YOKE_PROVIDER"):
        return os.environ["YOKE_PROVIDER"]
    if is_codex(executor or detect_executor()):
        return "openai"
    return "anthropic"


def detect_entrypoint() -> Optional[str]:
    """Detect the harness sub-entrypoint (e.g. ``claude-desktop``,
    ``claude-vscode``, ``codex-cli``).

    Sourced from ``CLAUDE_CODE_ENTRYPOINT`` for Claude Code, and from the
    full Codex entrypoint resolver (env -> transcript -> cache) when
    ``CODEX_THREAD_ID`` is set. Returns ``None`` when no entrypoint signal is
    exposed — callers should treat that as "unknown" rather than substituting
    a default, so telemetry stays truthful.
    """
    val = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
    if val:
        return val
    if os.environ.get("CODEX_THREAD_ID"):
        from runtime.harness.codex.codex_model import resolve_entrypoint

        return resolve_entrypoint()
    return None
