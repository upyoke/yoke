"""HC-progressive-disclosure-direction — tier citations cite forward.

Check A classifies Markdown, backticked, and bare path citations and warns on
missing or backward teaching references. Check B requires vague function-call
denials to name a registered function id or explicitly state that none exists.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from pathlib import Path
from typing import Iterable, List, Set, Tuple

from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
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


# Tier 1 is in-memory and always reachable from on-disk tiers.
TIER_DIRECTION_RULES: dict[int, frozenset[int]] = {
    0: frozenset({0, 1, 3}),
    2: frozenset({0, 1, 2, 3}),
    4: frozenset({0, 1, 3, 4}),
    5: frozenset({0, 1, 3, 4, 5}),
    6: frozenset({0, 1, 2, 3, 4, 5, 6}),
}


VAGUE_DENIAL_MARKERS: tuple[str, ...] = (
    "use function dispatch",
    "via the function-call surface",
    "use the function-call surface",
    "route through the function registry",
)

_NO_REGISTERED_NOTE = "no registered function id exists"

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
_COMMAND_SECTION_RE = re.compile(r"^### ([a-z][a-z0-9_-]*)\s*$")
_SKILL_ROOT = ".agents/skills/yoke"
_GENERATED_COMMAND_DOC = ".yoke/docs/commands.md"
_GENERATED_SKILL_REFERENCE_DOCS = frozenset(
    {_GENERATED_COMMAND_DOC, ".yoke/docs/lifecycle.md"}
)
_EXPLICIT_CITATION_ALIASES = {
    (".yoke/docs/lifecycle.md", "body-and-sync.md"): f"{_SKILL_ROOT}/idea/body-and-sync.md",
    (".yoke/docs/lifecycle.md", "infer-and-create.md"): f"{_SKILL_ROOT}/idea/infer-and-create.md",
    ("docs/harness-bootstrap.md", "manifest-schema.md"): "runtime/harness/manifest-schema.md",
    ("runtime/agents/boss.md", "db-reference.md"): ".yoke/docs/db-reference.md",
    ("runtime/agents/engineer.md", "session.md"): "runtime/harness/claude/rules/session.md",
    ("runtime/agents/tester.md", "session.md"): "runtime/harness/claude/rules/session.md",
    (f"{_SKILL_ROOT}/shared/tester-dispatch-template.md", "dispatch-context.md"): f"{_SKILL_ROOT}/conduct/dispatch-context.md",
}
_NON_TEACHING_PATH_LABELS = frozenset(
    {"product-designer-spec.md", "product-manager-spec.md"}
)
_EXPLICIT_DIRECTION_EDGES = frozenset(
    {
        ("AGENTS.md", ".yoke/docs/lifecycle.md"),
        ("AGENTS.md", "docs/harness-bootstrap.md"),
        ("runtime/harness/claude/rules/session.md", f"{_SKILL_ROOT}/idea/path-claim-blocking.md"),
        ("docs/OVERVIEW.md", f"{_SKILL_ROOT}/SKILL.md"),
        ("runtime/agents/architect.md", f"{_SKILL_ROOT}/conduct/entry-activation-resolution.md"),
    }
)


def _is_archive_relpath(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES)


def _classify_path(cited: str, repo_root: Path) -> int | None:
    """Return the tier for ``cited`` (repo-relative path), or None."""

    target = repo_root / cited
    if not target.is_file():
        return None
    if _is_archive_relpath(cited):
        return 6
    if cited == "CLAUDE.md":
        return 0
    if cited.startswith(".yoke/strategy/") and cited.endswith(".md"):
        return 3
    for tier, globs in TIER_GLOBS.items():
        if tier != 6 and any(fnmatch.fnmatch(cited, pattern) for pattern in globs):
            return tier
    if any(fnmatch.fnmatch(cited, pattern) for pattern in TIER_3_GLOBS):
        return 3
    if target.suffix == ".md":
        if cited.startswith(".agents/skills/yoke/"):
            return 5
        if cited.startswith("runtime/agents/"):
            return 4
        if cited.startswith(
            ("docs/", ".yoke/docs/", "ouroboros/", "runtime/harness/")
        ):
            return 3
    return None


def _normalize_cited(
    raw_cited: str,
    citing_rel: str,
    repo_root: Path,
    *,
    command_scope: str | None = None,
) -> str:
    """Resolve a local citation to one normalized repo-relative path."""

    cited = raw_cited.strip().split("#", 1)[0]
    root_prefixes = (
        ".agents/", ".claude/", ".codex/", ".yoke/",
        "docs/", "ouroboros/", "runtime/",
    )
    if cited.startswith(root_prefixes) or cited in {"AGENTS.md", "CLAUDE.md"}:
        normalized = posixpath.normpath(cited)
    else:
        normalized = posixpath.normpath(
            posixpath.join(posixpath.dirname(citing_rel), cited)
        )
    candidates = [
        _EXPLICIT_CITATION_ALIASES.get((citing_rel, cited)),
        normalized,
    ]
    if citing_rel.startswith(f"{_SKILL_ROOT}/"):
        skill_remainder = citing_rel.removeprefix(f"{_SKILL_ROOT}/")
        command_name = skill_remainder.split("/", 1)[0]
        candidates.append(
            posixpath.normpath(posixpath.join(_SKILL_ROOT, command_name, cited))
        )
    if command_scope:
        candidates.append(
            posixpath.normpath(posixpath.join(_SKILL_ROOT, command_scope, cited))
        )
    candidates.append(posixpath.normpath(posixpath.join(_SKILL_ROOT, cited)))
    if "/" not in cited and cited.endswith(".md"):
        candidates.extend(
            (
                posixpath.join("docs/archive/decisions", cited),
                posixpath.join(".yoke/strategy", cited),
            )
        )
    if cited.startswith("yoke/ouroboros/"):
        candidates.append(cited.removeprefix("yoke/"))
    for candidate in candidates:
        if candidate and (repo_root / candidate).is_file():
            return candidate
    if citing_rel in _GENERATED_SKILL_REFERENCE_DOCS and "/" not in cited:
        matches = [
            path for path in (repo_root / _SKILL_ROOT).glob(f"**/{cited}")
            if path.is_file()
        ]
        if len(matches) == 1:
            return matches[0].relative_to(repo_root).as_posix()
    return normalized


def _extract_citations(
    text: str,
    citing_rel: str,
    repo_root: Path,
) -> List[Tuple[int, str]]:
    """Return ``[(lineno, cited_path), ...]`` deduped per-line."""

    citations: List[Tuple[int, str]] = []
    command_scope: str | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if citing_rel == _GENERATED_COMMAND_DOC and raw.startswith("### "):
            section_match = _COMMAND_SECTION_RE.match(raw)
            command_scope = section_match.group(1) if section_match else None
        seen_on_line: Set[str] = set()
        for pattern in (_MARKDOWN_LINK_RE, _BACKTICK_PATH_RE, _BARE_PATH_RE):
            for match in pattern.finditer(raw):
                original = match.group(1).strip()
                if original.startswith(("http://", "https://", "mailto:")):
                    continue
                if original.split("#", 1)[0] in _NON_TEACHING_PATH_LABELS:
                    continue
                cited = _normalize_cited(
                    original,
                    citing_rel,
                    repo_root,
                    command_scope=command_scope,
                )
                if not cited.endswith((".json", ".md", ".py", ".toml")):
                    continue
                if not cited or cited in seen_on_line:
                    continue
                seen_on_line.add(cited)
                citations.append((lineno, cited))
    return citations


def _scan_check_a(
    rel: str,
    citing_tier: int,
    citations: Iterable[Tuple[int, str]],
    repo_root: Path,
    unclassified_seen: Set[str],
    findings: List[str],
) -> None:
    """Append Check A findings for one tier file in-place."""

    allowed = TIER_DIRECTION_RULES.get(citing_tier, frozenset())
    for lineno, cited in citations:
        if cited.endswith((".json", ".py", ".toml")):
            continue  # source/configuration asset, not teaching surface
        if cited == ".yoke/BOARD.md":
            continue  # generated board view, not a teaching surface
        cited_tier = _classify_path(cited, repo_root)
        if cited_tier is None:
            if cited in unclassified_seen:
                continue
            unclassified_seen.add(cited)
            findings.append(
                f"- {rel}:{lineno}: cited path {cited} is not classified "
                "into a teaching tier"
            )
            continue
        if _is_sanctioned_direction_edge(rel, cited):
            continue
        if cited_tier == 6 or cited_tier in allowed:
            continue
        findings.append(
            f"- {rel}:{lineno}: tier {citing_tier} file references "
            f"backward tier {cited_tier} file {cited}"
        )


def _is_sanctioned_direction_edge(citing: str, cited: str) -> bool:
    """Return whether a narrow, named cross-tier citation is intentional."""

    if (citing, cited) in _EXPLICIT_DIRECTION_EDGES:
        return True
    if citing == _GENERATED_COMMAND_DOC and cited.startswith(f"{_SKILL_ROOT}/"):
        return True
    if (
        citing == ".yoke/docs/lifecycle.md"
        and cited.startswith(f"{_SKILL_ROOT}/idea/")
    ):
        return True
    if (
        citing == "docs/harness-bootstrap.md"
        and cited.startswith(f"{_SKILL_ROOT}/")
    ):
        return True
    return False


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
        citations = _extract_citations(text, rel, repo_root)
        _scan_check_a(rel, tier, citations, repo_root, unclassified_seen, findings)
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
