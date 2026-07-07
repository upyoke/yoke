"""Sweep gate: no tracked content references the retired repo-root
``strategy/<slug>.md`` location for the strategy docs.

The rendered views moved to ``.yoke/strategy/`` (per-project, resolver
``yoke_core.domain.strategy_docs_paths``). The old root location is an
obsoleted path: any tracked file that still teaches it would point
agents at files that no longer exist. Exclusions:

* ``docs/archive/`` + ``docs/archive/legacy-plan-artifacts/`` — historical record
  surfaces (the obsoleted-terms precedent).
* ``.yoke/strategy/`` — the doc BODIES are DB content; self-references
  inside them are updated through the ingest/replace path, not git.
* This gate and the resolver tests, which assert the legacy shape is
  rejected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_DOC_SLUGS = (
    "MISSION", "VISION", "PAD", "PROMPTS", "WISPS",
    "LANDSCAPE", "MASTER-PLAN", "LEGACY-NOTES", "FUTURE-NOTES",
)

_NEEDLES = tuple(f"strategy/{slug}.md" for slug in _DOC_SLUGS)
_RETIRED_STRATEGY_SLUGS = (
    "FOUNDATION-RUNTIME-NOTES",
    "CLOUD-RUNTIME-NOTES",
)

_EXEMPT_PREFIXES = (
    "docs/archive/",
    "docs/archive/legacy-plan-artifacts/",
    ".yoke/strategy/",
    "runtime/api/test_strategy_path_sweep_gate.py",
    # Asserts slug_from_view_path rejects the legacy root location.
    "runtime/api/domain/test_strategy_docs_defaults.py",
)


def _tracked_files() -> list:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=30,
        check=True,
    )
    return [p for p in result.stdout.split("\0") if p]


def _violations_in(rel: str, text: str) -> list:
    hits = []
    for needle in _NEEDLES:
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx < 0:
                break
            start = idx + 1
            # The current location embeds the same substring after
            # ".yoke/" — only the bare root form is a violation.
            if text[max(0, idx - 6):idx] == ".yoke/":
                continue
            line = text.count("\n", 0, idx) + 1
            hits.append(f"{rel}:{line}: {needle}")
    return hits


def test_no_tracked_reference_to_retired_strategy_root() -> None:
    violations = []
    for rel in _tracked_files():
        if any(rel.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            continue
        path = _REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        violations.extend(_violations_in(rel, text))
    assert not violations, (
        "tracked content still references the retired repo-root strategy "
        "location (rendered views live under .yoke/strategy/, resolver "
        "yoke_core.domain.strategy_docs_paths):\n" + "\n".join(violations)
    )


def test_no_live_reference_to_retired_strategy_slugs() -> None:
    violations = []
    for rel in _tracked_files():
        if any(rel.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            continue
        path = _REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for slug in _RETIRED_STRATEGY_SLUGS:
            start = 0
            while True:
                idx = text.find(slug, start)
                if idx < 0:
                    break
                start = idx + 1
                line = text.count("\n", 0, idx) + 1
                violations.append(f"{rel}:{line}: {slug}")
    assert not violations, (
        "tracked live content references retired strategy slugs:\n"
        + "\n".join(violations)
    )
