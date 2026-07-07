"""HC-tier-module-path-resolution — cited Python module paths must resolve.

Teaching prose in Tier 0/2/4/5 surfaces routinely names ``runtime.api.*``
dotted module paths (e.g. ``yoke_core.domain.yoke_function_dispatch``).
A confabulated module name (e.g. ``yoke_core.domain.yoke_function_envelope``
when the real module is ``yoke_function_models``) silently teaches the
agent a broken import — the canonical 2026-05-14 incident.

This HC regex-scans each scannable tier file for ``runtime.<segment>``
dotted paths (depth >= 2 after ``runtime.``), then resolves each cited
path via :func:`importlib.util.find_spec`. Misses get one fallback try
as a sub-symbol reference: split off the final segment and ``getattr``
the parent module to confirm the symbol exists.

Fenced ``text`` and ``diff`` code blocks are exempt — those carry
illustrative output, not live module references. ``python`` and
``bash`` fences ARE scanned because those are teaching code.

Severity is WARN in v0. Truncate output to ``_MAX_FINDINGS`` lines.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
from typing import List, Tuple

from yoke_core.engines.doctor_registry_tier_discipline import (
    TIER_6_ARCHIVE_PREFIXES,
    TIER_GLOBS,  # noqa: F401  — re-exported so importers reach it here
    iter_tier_paths,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "HC-tier-module-path-resolution"
HC_LABEL = (
    "Tier 0/2/4/5 surface cites a runtime.api.* module that does not resolve"
)
_MAX_FINDINGS = 40


# Fence languages exempt from scanning (illustrative output, not teaching
# code that an agent would import). ``python`` and ``bash`` fences are NOT
# in this set because they teach live invocations.
_EXEMPT_FENCE_LANGS: frozenset[str] = frozenset({"text", "diff"})


# Dotted-path matcher for the Yoke package roots: ``runtime.*`` (the
# pre-split namespace, still live mid-cut) plus the four post-split
# packages (``yoke_contracts`` / ``yoke_cli`` / ``yoke_harness`` /
# ``yoke_core``). We require at least two segments after the root
# (e.g. ``yoke_core.domain``, ``yoke_contracts.api.function_call``)
# so plain nouns like ``runtime.config`` in prose do not trip. The final
# segment must end in an alphanumeric character so ``watch_*`` (regex-
# truncated to ``watch_``) does not register as a citation — real Python
# module names do not end in a trailing underscore.
_MODULE_ROOTS: Tuple[str, ...] = (
    "runtime",
    "yoke_contracts",
    "yoke_cli",
    "yoke_harness",
    "yoke_core",
)
_DOTTED_PATH_RE = re.compile(
    r"\b(?:" + "|".join(_MODULE_ROOTS) + r")"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*){1,}\.[A-Za-z_][A-Za-z0-9_]*[A-Za-z0-9]\b"
)


# Universal teaching-placeholder leaf segments. Authors write
# ``yoke_core.domain.foo`` / ``foo.bar`` / ``other_module`` / a bare
# ``X`` as schematic stand-ins, not as live citations. Excluding by
# leaf-segment identity (not by parent) keeps the placeholder filter
# narrow — a real module accidentally named ``foo`` would still fire
# because it would resolve, and the HC only emits on non-resolution.
_PLACEHOLDER_LEAF_SEGMENTS: frozenset[str] = frozenset(
    {"foo", "bar", "baz", "qux", "X", "Y", "Z", "N", "other_module"}
)


def _is_archive_relpath(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES)


def _fence_lang(stripped: str) -> str | None:
    """Return the lang token after a triple-backtick fence, or ``""``.

    ``stripped`` is the leading-whitespace-stripped line. A bare fence
    returns ``""``; ``text`` returns ``"text"``. Returns ``None`` when
    the line is not a fence opener at all.
    """

    if not stripped.startswith("```"):
        return None
    return stripped[3:].strip().split(None, 1)[0].lower() if stripped[3:].strip() else ""


def _resolve_module_path(dotted: str) -> bool:
    """Return True when ``dotted`` resolves as a module or known sub-symbol.

    Step 1: :func:`importlib.util.find_spec` on the dotted path. A non-None
    spec means the module exists — PASS.

    Step 2: split off the final segment and try ``find_spec`` on the parent.
    If the parent exists, ``import_module`` the parent and ``hasattr`` for
    the trailing symbol. Top-level import failures on the parent are
    treated as non-resolution (the citation is broken in either case).
    """

    try:
        spec = importlib.util.find_spec(dotted)
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        spec = None
    if spec is not None:
        return True

    if "." not in dotted:
        return False
    parent, _, leaf = dotted.rpartition(".")
    try:
        parent_spec = importlib.util.find_spec(parent)
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return False
    if parent_spec is None:
        return False
    try:
        parent_mod = importlib.import_module(parent)
    except Exception:  # noqa: BLE001 — broken import is non-resolution
        return False
    return hasattr(parent_mod, leaf)


def _scan_file(rel: str, text: str) -> List[Tuple[int, str]]:
    """Return ``[(lineno, dotted_path), ...]`` for citations to verify.

    Skips fenced blocks whose language is in :data:`_EXEMPT_FENCE_LANGS`.
    Bare fences with no language are treated as scannable — prose authors
    routinely open fences without a language tag, and module citations
    inside untagged fences are still live teaching references.
    """

    citations: List[Tuple[int, str]] = []
    in_exempt_fence = False
    in_any_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            if in_any_fence:
                in_any_fence = False
                in_exempt_fence = False
            else:
                lang = _fence_lang(stripped) or ""
                in_any_fence = True
                in_exempt_fence = lang in _EXEMPT_FENCE_LANGS
            continue
        if in_exempt_fence:
            continue
        for match in _DOTTED_PATH_RE.finditer(raw):
            dotted = match.group(0)
            if _has_placeholder_segment(dotted):
                continue
            citations.append((lineno, dotted))
    return citations


def _has_placeholder_segment(dotted: str) -> bool:
    """Return True when ``dotted`` contains a universal placeholder leaf.

    Authors use ``yoke_core.domain.foo`` / ``.foo.bar`` and similar
    constructs as schematic stand-ins. Any single segment matching one
    of :data:`_PLACEHOLDER_LEAF_SEGMENTS` marks the whole citation as
    illustrative — segment identity, not position, because authors put
    placeholders both at the leaf and mid-path (``foo.bar``).
    """

    return any(seg in _PLACEHOLDER_LEAF_SEGMENTS for seg in dotted.split("."))


def _scan_all(repo_root: Path) -> List[str]:
    findings: List[str] = []
    resolved: dict[str, bool] = {}  # per-run cache; find_spec itself caches.
    for _tier, abs_path in iter_tier_paths(repo_root):
        rel = abs_path.relative_to(repo_root).as_posix()
        if _is_archive_relpath(rel):
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, dotted in _scan_file(rel, text):
            ok = resolved.get(dotted)
            if ok is None:
                ok = _resolve_module_path(dotted)
                resolved[dotted] = ok
            if not ok:
                findings.append(
                    f"- {rel}:{lineno}: unresolved module path {dotted}"
                )
    return findings


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more findings")
    return "\n".join(truncated)


def hc_tier_module_path_resolution(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-tier-module-path-resolution: verify runtime.* citations resolve."""

    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "repo root not resolvable (skip)")
        return

    findings = _scan_all(Path(repo_root))
    if findings:
        rec.record(HC_SLUG, HC_LABEL, "WARN", _format_detail(findings))
    else:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "")


__all__ = [
    "hc_tier_module_path_resolution",
    "HC_SLUG",
    "HC_LABEL",
]
