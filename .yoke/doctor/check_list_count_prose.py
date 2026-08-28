"""Flag a stated list length sitting next to the markdown list it counts.

Authored teaching prose that names how many entries a nearby list has is a
second copy of a fact the list already carries. Editing the list silently
makes the sentence lie. This check covers the high-signal form: a spelled-out
or decimal quantity on a colon-terminated intro immediately before a markdown
list. A stated length of one is ordinary English, not a duplicated length, so
it is ignored.

Agreement is still a hit. A matching count is the duplicate; the list is the
source of truth. Nouns are word-bounded and omit line-limits, timeouts, and
ports so those facts do not fire.

``docs/archive/`` is historical record. Rendered harness adapters mirror
``runtime/agents/``; fix the canonical body. The install-bundle snapshot is
generated from source. Execution-instruction rows are scanned because they
are teaching prose stored in the control plane, not files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from yoke_core.domain.agents_render_conditional import RENDERED_AGENT_DIRS
from yoke_core.domain.db_helpers import query_rows
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
    _table_exists,
)
from yoke_core.engines.doctor_tree_scan import iter_tree_files
from yoke_project_checks._declare import self_project_checks

HC_SLUG = "list-count-prose"
HC_NAME = "No stated count of an adjacent markdown list"
HC_ID = f"HC-{HC_SLUG}"

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_NOUN = (
    r"rules?|steps?|parts?|fields?|axes|checks?|checkpoints?|"
    r"categor(?:y|ies)|failures?|values?|ways|commands?|"
    r"stages?|phases?|events?|gates?|reasons?|indexes"
)
_QUANTITY = re.compile(
    r"(?i)(?:(?:these|the\s+following|follows?|exactly(?:\s+these)?|all)\s+)?"
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\b"
    r"(?:\s+[A-Za-z][A-Za-z-]*)?"
    r"\s+"
    rf"\b(?:{_NOUN})\b"
)
_LIST_ITEM = re.compile(r"^(?P<indent> {0,3})(?:[-*+]|\d+\.)\s+")

_SCAN_ROOTS: tuple[str, ...] = (
    ".agents",
    "runtime/agents",
    "runtime/harness",
    "docs",
)
_SCAN_SUFFIXES = frozenset({".md"})
_ARCHIVE_PREFIX = "docs/archive/"
_BUNDLE_PREFIX = "packages/yoke-core/src/yoke_core/install_bundle_tree/"
_ROOT_RULE_FILES = ("AGENTS.md",)


@dataclass(frozen=True)
class ListCountHit:
    """One stated quantity sitting immediately before a markdown list."""

    line: int
    stated: int
    actual: int
    snippet: str


def _parse_count(token: str) -> Optional[int]:
    folded = token.lower()
    if folded in _NUMBER_WORDS:
        return _NUMBER_WORDS[folded]
    if token.isdigit():
        value = int(token)
        return value if value > 0 else None
    return None


def _last_quantity(line: str) -> Optional[int]:
    found: Optional[int] = None
    for match in _QUANTITY.finditer(line):
        parsed = _parse_count(match.group(1))
        if parsed is not None:
            found = parsed
    return found


def _list_indent(line: str) -> Optional[int]:
    match = _LIST_ITEM.match(line)
    return None if match is None else len(match.group("indent"))


def _count_list(lines: List[str], start: int) -> int:
    indent = _list_indent(lines[start])
    if indent is None:
        return 0
    total = 0
    index = start
    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            index += 1
            continue
        found = _list_indent(raw)
        if found is None:
            if raw.startswith(" ") or raw.startswith("\t"):
                index += 1
                continue
            break
        if found == indent:
            total += 1
        elif found < indent:
            break
        index += 1
    return total


def _end_of_list(lines: List[str], start: int) -> int:
    indent = _list_indent(lines[start])
    if indent is None:
        return start + 1
    index = start
    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            index += 1
            continue
        found = _list_indent(raw)
        if found is None:
            if raw.startswith(" ") or raw.startswith("\t"):
                index += 1
                continue
            break
        if found < indent:
            break
        index += 1
    return max(index, start + 1)


def scan_markdown_list_counts(text: str) -> List[ListCountHit]:
    """Return hits for a single teaching document or instruction body."""
    lines = text.splitlines()
    hits: List[ListCountHit] = []
    index = 0
    while index < len(lines):
        if _list_indent(lines[index]) is None:
            index += 1
            continue
        prior = index - 1
        while prior >= 0 and not lines[prior].strip():
            prior -= 1
        if prior >= 0 and _list_indent(lines[prior]) is None:
            intro = lines[prior].rstrip()
            stated = _last_quantity(intro)
            if intro.endswith(":") and stated is not None and stated > 1:
                actual = _count_list(lines, index)
                hits.append(
                    ListCountHit(
                        line=prior + 1,
                        stated=stated,
                        actual=actual,
                        snippet=lines[prior].strip()[:120],
                    )
                )
        index = _end_of_list(lines, index)
    return hits


def _is_generated_output(relative: str) -> bool:
    if relative.startswith(_ARCHIVE_PREFIX) or relative.startswith(_BUNDLE_PREFIX):
        return True
    return any(
        relative == directory.as_posix()
        or relative.startswith(f"{directory.as_posix()}/")
        for directory in RENDERED_AGENT_DIRS
    )


def _iter_teaching_files(repo_root: Path) -> Iterable[Path]:
    for name in _ROOT_RULE_FILES:
        path = repo_root / name
        if path.is_file() and not path.is_symlink():
            yield path
    for root_name in _SCAN_ROOTS:
        base = repo_root / root_name
        if not base.is_dir():
            continue
        for path in iter_tree_files(base, "*.md"):
            if path.suffix not in _SCAN_SUFFIXES or not path.is_file():
                continue
            relative = path.relative_to(repo_root).as_posix()
            if _is_generated_output(relative):
                continue
            yield path


def scan_teaching_surfaces(repo_root: Path) -> List[str]:
    """Return ``path:line:`` findings for authored teaching files."""
    findings: List[str] = []
    for path in _iter_teaching_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for hit in scan_markdown_list_counts(text):
            findings.append(
                f"{relative}:{hit.line}: stated {hit.stated}, list has "
                f"{hit.actual} — {hit.snippet}"
            )
    return findings


def scan_execution_instruction_rows(conn) -> List[str]:
    """Return findings for control-plane execution-instruction bodies."""
    if conn is None or not _table_exists(conn, "workflow_execution_instructions"):
        return []
    rows = query_rows(
        conn,
        "SELECT id, content FROM workflow_execution_instructions",
    )
    findings: List[str] = []
    for row in rows:
        body = str(row["content"] or "")
        instruction_id = row["id"]
        for hit in scan_markdown_list_counts(body):
            findings.append(
                f"workflow_execution_instructions id={instruction_id}:"
                f"{hit.line}: stated {hit.stated}, list has {hit.actual} — "
                f"{hit.snippet}"
            )
    return findings


def hc_list_count_prose(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-list-count-prose: stated quantity adjacent to the list it counts."""
    del args
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(HC_ID, HC_NAME, "PASS", "No repo root resolved — skipping.")
        return
    findings = scan_teaching_surfaces(Path(repo_root_str))
    findings.extend(scan_execution_instruction_rows(conn))
    if not findings:
        rec.record(HC_ID, HC_NAME, "PASS", "")
        return
    rec.record(
        HC_ID,
        HC_NAME,
        "FAIL",
        "Authored teaching prose states a count of an adjacent markdown list. "
        "Drop the number; the list already carries the length "
        f"({len(findings)} hit(s)):\n"
        + "\n".join(findings[:40])
        + (f"\n... and {len(findings) - 40} more" if len(findings) > 40 else ""),
    )


PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_NAME, hc_list_count_prose),
)

__all__ = [
    "HC_ID",
    "HC_NAME",
    "HC_SLUG",
    "ListCountHit",
    "PROJECT_HEALTH_CHECKS",
    "hc_list_count_prose",
    "scan_execution_instruction_rows",
    "scan_markdown_list_counts",
    "scan_teaching_surfaces",
]
