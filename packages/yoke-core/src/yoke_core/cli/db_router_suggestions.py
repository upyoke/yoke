"""Nearest-match suggestion helpers for unknown db_router tokens.

Provides a generic edit-distance ranker plus two operator-facing hint
emitters used by ``db_router.py`` on unknown-domain and unknown-items-
subcommand paths. The denial-time hint names a likely intended target
instead of dumping the entire subcommand inventory; callers can still
ask for the full inventory via ``--list-subcommands`` / ``help``.

The module is intentionally generic so the same nearest-match shape
covers every domain whose denial path eventually wires through here.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Iterable, List, Optional, Sequence, TextIO


def _edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance (case-insensitive)."""
    a = a.lower()
    b = b.lower()
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ac in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, bc in enumerate(b, 1):
            cost = 0 if ac == bc else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _adaptive_threshold(target: str) -> int:
    """Allow more slack for longer typed tokens; tight for short ones."""
    n = len(target)
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    return 3


def nearest_matches(
    target: str,
    candidates: Iterable[str],
    *,
    max_results: int = 3,
    max_distance: Optional[int] = None,
) -> List[str]:
    """Return up to ``max_results`` candidates ranked by similarity.

    Pure function — no I/O, deterministic output for the same inputs.
    """
    if not target:
        return []
    threshold = (
        max_distance if max_distance is not None else _adaptive_threshold(target)
    )
    scored: List[tuple] = []
    for cand in candidates:
        d = _edit_distance(target, cand)
        if d <= threshold:
            scored.append((d, cand))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _, c in scored[:max_results]]


def format_unknown_token_hint(
    token: str,
    kind: str,
    candidates: Sequence[str],
    *,
    list_subcommands_hint: Optional[str] = None,
) -> str:
    """Render a multi-line hint for an unknown token.

    Includes a `Did you mean ...?` line when at least one candidate is
    within threshold, falls through to a `No close match` line otherwise,
    and appends an optional list-subcommands fallback so the operator can
    still discover the full inventory when needed.
    """
    matches = nearest_matches(token, candidates)
    lines: List[str] = []
    if matches:
        if len(matches) == 1:
            lines.append(f"Did you mean: '{matches[0]}'?")
        else:
            shown = ", ".join(f"'{m}'" for m in matches)
            lines.append(f"Did you mean one of: {shown}?")
    else:
        lines.append(f"No close match for {kind} '{token}'.")
    if list_subcommands_hint:
        lines.append(list_subcommands_hint)
    return "\n".join(lines)


def emit_unknown_domain_hint(domain: str, stream: Optional[TextIO] = None) -> None:
    """Emit unknown-domain error line + nearest-match hint to *stream*."""
    out = stream if stream is not None else sys.stderr
    # Lazy import keeps db_router_help unloaded for callers that only want
    # the pure ranker (`nearest_matches`).
    from yoke_core.cli.db_router_help import ALL_DOMAINS
    print(f"Error: unknown domain '{domain}'", file=out)
    print(
        format_unknown_token_hint(
            domain,
            kind="domain",
            candidates=ALL_DOMAINS,
            list_subcommands_hint=(
                "Run `python3 -m yoke_core.cli.db_router help` "
                "for the full domain list."
            ),
        ),
        file=out,
    )


def emit_unknown_items_subcmd_hint(
    subcmd: str, stream: Optional[TextIO] = None,
) -> None:
    """Emit unknown-items-subcommand error + nearest-match hint to *stream*."""
    out = stream if stream is not None else sys.stderr
    from yoke_core.cli.db_router_dispatch import (
        _ITEMS_READ_SUBCMDS,
        _ITEMS_WRITE_SUBCMDS,
    )
    candidates = sorted(set(_ITEMS_READ_SUBCMDS) | set(_ITEMS_WRITE_SUBCMDS))
    print(f"Error: unknown items subcommand '{subcmd}'", file=out)
    print(
        format_unknown_token_hint(
            subcmd,
            kind="items subcommand",
            candidates=candidates,
            list_subcommands_hint=(
                "Run `python3 -m yoke_core.cli.db_router items --list-subcommands` "
                "for the full subcommand list."
            ),
        ),
        file=out,
    )


def _subcommands_from_parser(module_name: str) -> List[str]:
    """Best-effort argparse subcommand inventory for a routed domain module."""
    try:
        mod = import_module(module_name)
    except ImportError:
        return []
    builder = getattr(mod, "_build_parser", None) or getattr(mod, "build_parser", None)
    if builder is None:
        return []
    try:
        parser = builder()
    except Exception:
        return []
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and choices:
            return sorted(str(c) for c in choices)
    return []


def emit_unknown_domain_subcmd_hint(
    domain: str,
    module_name: str,
    remaining: Sequence[str],
    stream: Optional[TextIO] = None,
) -> bool:
    """Emit a nearest-match hint for routed-domain subcommand typos.

    Returns True when a hint was emitted and the caller should stop with
    usage exit 2. Returns False when the domain has no introspectable
    subcommand inventory or the requested subcommand is known.
    """
    if not remaining or remaining[0].startswith("-"):
        return False
    subcmd = remaining[0]
    candidates = _subcommands_from_parser(module_name)
    if not candidates or subcmd in candidates:
        return False
    out = stream if stream is not None else sys.stderr
    print(f"Error: unknown {domain} subcommand '{subcmd}'", file=out)
    print(
        format_unknown_token_hint(
            subcmd,
            kind=f"{domain} subcommand",
            candidates=candidates,
            list_subcommands_hint=(
                "Run `python3 -m yoke_core.cli.db_router "
                f"{domain} --help` for the full subcommand list."
            ),
        ),
        file=out,
    )
    return True


__all__ = [
    "nearest_matches",
    "format_unknown_token_hint",
    "emit_unknown_domain_hint",
    "emit_unknown_domain_subcmd_hint",
    "emit_unknown_items_subcmd_hint",
]
