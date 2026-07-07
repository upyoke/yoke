"""HC-progressive-disclosure-direction — tier citations cite forward.

Yoke's teaching tiers form a directed citation graph: Tier 0/2/4/5
files cite *toward* Tier 1 (the auto-loaded packet) and Tier 3 (the
reference catalogs), with same-tier and sanctioned forward-direction
references also allowed. Backward references (e.g. AGENTS.md citing a
SKILL.md as authoritative) invert the disclosure direction.

**Check A — tier-direction citations.** Extract cited paths from
markdown links, backticked path mentions, and bare-prefixed mentions.
Skip ``.py`` source-code citations (API references, not teaching
references). Reverse-lookup each cited path against ``TIER_GLOBS``
and ``TIER_3_GLOBS``; emit a backward-tier finding when the cited
tier is not in ``TIER_DIRECTION_RULES[citing]``. Unclassified cited
paths emit one WARN per unique path.

**Check B — vague-denial specificity.** Lines containing any substring
in ``VAGUE_DENIAL_MARKERS`` must name a concrete registered function
id (substring of any ``REQUIRED_FUNCTION_IDS`` entry) or carry the
explicit absence note ``"no registered function id exists"``.

Severity is WARN in v0; findings are truncated to ``_MAX_FINDINGS``.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Iterable, List, Set, Tuple

from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
    TIER_1_GLOBS,  # noqa: F401  — re-exported so importers reach it here
    TIER_3_GLOBS,
    TIER_6_ARCHIVE_PREFIXES,
    TIER_GLOBS,
    iter_tier_paths,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "HC-progressive-disclosure-direction"
HC_LABEL = "Backward tier reference or vague denial without concrete function id"
_MAX_FINDINGS = 40


# Allowed citation direction per citing tier. Tier 1 lives in-memory
# (no on-disk surface), so it is always reachable from on-disk tiers.
TIER_DIRECTION_RULES: dict[int, frozenset[int]] = {
    0: frozenset({0, 1, 3}),
    2: frozenset({1, 2, 3}),
    4: frozenset({1, 3, 4}),
    5: frozenset({1, 3, 4, 5}),
    6: frozenset({0, 1, 2, 3, 4, 5, 6}),
}


# Vague-denial substrings — directive phrases that elide the concrete
# function id. Lines containing any of these MUST also name a registered
# function id or carry the explicit-absence note.
VAGUE_DENIAL_MARKERS: tuple[str, ...] = (
    "use function dispatch",
    "via the function-call surface",
    "use the function-call surface",
    "route through the function registry",
)

_NO_REGISTERED_NOTE = "no registered function id exists"

# Citation patterns: markdown link, backticked teaching-extension path,
# bare prefixed path. Python sources are filtered downstream.
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK_PATH_RE = re.compile(
    r"`([a-zA-Z0-9_/.][a-zA-Z0-9_/.\\-]*\.(?:md|toml|json))`"
)
_BARE_PATH_RE = re.compile(
    r"(?<![/\w])("
    r"(?:runtime|docs|\.agents)/[\w/.\\-]+\.(?:md|toml|json|py)"
    r"|AGENTS\.md|CLAUDE\.md"
    r")(?![\w/])"
)


def _is_archive_relpath(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES)


def _classify_path(cited: str) -> int | None:
    """Return the tier for ``cited`` (repo-relative path), or None."""

    if _is_archive_relpath(cited):
        return 6
    for pattern in TIER_3_GLOBS:
        if fnmatch.fnmatch(cited, pattern):
            return 3
    for tier, globs in TIER_GLOBS.items():
        if tier == 6:
            continue
        for pattern in globs:
            if fnmatch.fnmatch(cited, pattern):
                return tier
    return None


def _normalize_cited(raw_cited: str) -> str:
    """Strip fragments and leading ``./`` or ``../`` segments."""
    cited = raw_cited.strip().split("#", 1)[0]
    while cited.startswith("../"):
        cited = cited[3:]
    if cited.startswith("./"):
        cited = cited[2:]
    return cited


def _extract_citations(text: str) -> List[Tuple[int, str]]:
    """Return ``[(lineno, cited_path), ...]`` deduped per-line."""

    citations: List[Tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        seen_on_line: Set[str] = set()
        for pattern in (_MARKDOWN_LINK_RE, _BACKTICK_PATH_RE, _BARE_PATH_RE):
            for match in pattern.finditer(raw):
                original = match.group(1).strip()
                if original.startswith(("http://", "https://", "mailto:")):
                    continue
                cited = _normalize_cited(original)
                if not cited or cited in seen_on_line:
                    continue
                seen_on_line.add(cited)
                citations.append((lineno, cited))
    return citations


def _scan_check_a(
    rel: str,
    citing_tier: int,
    citations: Iterable[Tuple[int, str]],
    unclassified_seen: Set[str],
    findings: List[str],
) -> None:
    """Append Check A findings for one tier file in-place."""

    allowed = TIER_DIRECTION_RULES.get(citing_tier, frozenset())
    for lineno, cited in citations:
        if cited.endswith(".py"):
            continue  # source-code citation, not teaching surface
        cited_tier = _classify_path(cited)
        if cited_tier is None:
            if cited in unclassified_seen:
                continue
            unclassified_seen.add(cited)
            findings.append(
                f"- {rel}:{lineno}: cited path {cited} is not classified "
                "into a teaching tier"
            )
            continue
        if cited_tier == 6 or cited_tier in allowed:
            continue
        findings.append(
            f"- {rel}:{lineno}: tier {citing_tier} file references "
            f"backward tier {cited_tier} file {cited}"
        )


def _scan_check_b(rel: str, text: str, findings: List[str]) -> None:
    """Append Check B findings for one tier file in-place."""

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not any(marker in raw for marker in VAGUE_DENIAL_MARKERS):
            continue
        if _NO_REGISTERED_NOTE in raw:
            continue
        if any(fn in raw for fn in REQUIRED_FUNCTION_IDS):
            continue
        findings.append(
            f"- {rel}:{lineno}: vague-denial phrase used without a "
            "concrete registered function id (REQUIRED_FUNCTION_IDS) "
            "or the explicit 'no registered function id exists' note"
        )


def _scan_all(repo_root: Path) -> List[str]:
    findings: List[str] = []
    unclassified_seen: Set[str] = set()
    for tier, abs_path in iter_tier_paths(repo_root):
        rel = abs_path.relative_to(repo_root).as_posix()
        if _is_archive_relpath(rel):
            continue  # defense-in-depth (iter_tier_paths already skips)
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        citations = _extract_citations(text)
        _scan_check_a(rel, tier, citations, unclassified_seen, findings)
        _scan_check_b(rel, text, findings)
    return findings


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more findings")
    return "\n".join(truncated)


def hc_progressive_disclosure_direction(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-progressive-disclosure-direction: forward-only tier citations."""

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
    "hc_progressive_disclosure_direction",
    "HC_SLUG",
    "HC_LABEL",
    "TIER_DIRECTION_RULES",
    "VAGUE_DENIAL_MARKERS",
]
