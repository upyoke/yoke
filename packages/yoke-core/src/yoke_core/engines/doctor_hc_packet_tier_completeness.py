"""HC-packet-tier-completeness — role packet covers workflow surface.

The Tier 1 packet (rendered by :func:`render_role_packet`) is the
single authoritative schema/CLI surface for each role. When skill
prose for a role references a ``<table>.<column>`` the role's packet
does NOT enumerate, conduct-time confabulation follows.

**Check A — referenced columns are in the role's packet.** For each
role in :data:`ROLE_TOPICS`, scan ``SKILL_SCAN_TARGETS[role]`` for
``\\b<table>.<column>\\b`` patterns where ``<table>`` is canonical.
Reverse-lookup to its topic via :data:`TOPIC_TABLES`, locate the
section + ``**`` + backtick + table-name + backtick + ``**`` bullet
in the rendered packet, and assert ``<column>`` is in the bullet
text. Section-anchored matching keeps a column appearing in a
neighbouring table's bullet from masking the real miss.

**Check B — function-call envelope (main_agent only).** Packet must
contain ``actor``, ``session_id``, ``actor_id``, ``preconditions``,
``options``, plus at least one substring from
:data:`REQUIRED_FUNCTION_IDS`.

Missing skill files emit a distinct WARN (``SKILL_SCAN_TARGETS
contains missing skill path``). Empty ``SKILL_SCAN_TARGETS[role]``
skips the role cleanly. Severity is WARN in v0; findings are
truncated to ``_MAX_FINDINGS``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from yoke_core.domain.schema_api_context import render_role_packet
from yoke_core.domain.schema_api_context_seed import (
    ROLE_TOPICS,
    TOPIC_TABLES,
)
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES
from yoke_core.engines.doctor_registry_tier_discipline import (
    REQUIRED_FUNCTION_IDS,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "HC-packet-tier-completeness"
HC_LABEL = "Role packet missing structural fact referenced by workflow"
_MAX_FINDINGS = 40


# Paths each role's typical workflow invokes. Verified live 2026-05-16
# against the worktree; staleness emits a distinct WARN rather than a
# packet-completeness FAIL so the HC stays useful even when a skill
# file is renamed.
SKILL_SCAN_TARGETS: Dict[str, Tuple[str, ...]] = {
    "main_agent": (
        ".agents/skills/yoke/conduct/SKILL.md",
        ".agents/skills/yoke/advance/SKILL.md",
        ".agents/skills/yoke/refine/SKILL.md",
        ".agents/skills/yoke/polish/SKILL.md",
        ".agents/skills/yoke/usher/SKILL.md",
        ".agents/skills/yoke/idea/SKILL.md",
        ".agents/skills/yoke/do/SKILL.md",
    ),
    "engineer_agent": (
        ".agents/skills/yoke/conduct/engineer-tester-dispatch.md",
        ".agents/skills/yoke/conduct/engineer-tester-loop.md",
        ".agents/skills/yoke/conduct/engineer-tester-closeout.md",
        ".agents/skills/yoke/conduct/dispatch-context-prompts.md",
        ".agents/skills/yoke/advance/SKILL.md",
    ),
    "tester_agent": (
        ".agents/skills/yoke/conduct/engineer-tester-dispatch.md",
        ".agents/skills/yoke/conduct/engineer-tester-loop.md",
        ".agents/skills/yoke/conduct/engineer-tester-closeout.md",
        ".agents/skills/yoke/conduct/dispatch-context-prompts.md",
    ),
    "architect_agent": (
        ".agents/skills/yoke/shepherd/SKILL.md",
        ".agents/skills/yoke/shepherd/design-and-plan.md",
        ".agents/skills/yoke/shepherd/plan-handoff.md",
        ".agents/skills/yoke/shepherd/planning-to-planned-gates.md",
    ),
    "boss_agent": (
        ".agents/skills/yoke/shepherd/boss-verdict.md",
        ".agents/skills/yoke/shepherd/boss-verdict-rubric.md",
        ".agents/skills/yoke/shepherd/boss-verdict-transitions.md",
    ),
    "simulator_agent": (
        ".agents/skills/yoke/simulate/SKILL.md",
        ".agents/skills/yoke/simulate/epic-flow.md",
        ".agents/skills/yoke/simulate/autofix-loop.md",
    ),
}


# Reverse-lookup: table -> topic. Built once at module import.
_TABLE_TOPIC: Dict[str, str] = {
    table: topic for topic, tables in TOPIC_TABLES.items() for table in tables
}


# Class-A bleed pattern (word-boundary <table>.<column>). Same shape
# the schema-bleed HC uses; reused here to grow with CANONICAL_TABLES.
_TABLE_COL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")

# Schema-cheat-sheet bullet anchor. Matches lines like:
#   - **`items`** — `id, title, ...`
# The leading ``- `` is the markdown bullet marker; ``**`` + backtick
# table + backtick + ``**`` is the canonical bullet head per the spec.
_BULLET_HEAD_RE = re.compile(r"^- \*\*`([a-z_][a-z0-9_]*)`\*\*", re.MULTILINE)
# A new bullet line at top-level (``- **`` or ``- ` ``) or the next
# section header (``### ``) closes the previous bullet.
_BULLET_END_RE = re.compile(r"(?m)^(?:- \*\*|- `|### )")
# Section header (``### DB Quick Reference — <topic> ...``).
_SECTION_HEAD_RE = re.compile(
    r"^### DB Quick Reference — (\S+)", re.MULTILINE
)

# Envelope essentials (Check B). All must appear in main_agent packet.
_ENVELOPE_FIELDS: Tuple[str, ...] = (
    "actor",
    "session_id",
    "actor_id",
    "preconditions",
    "options",
)


def _section_chunks(packet: str) -> Dict[str, str]:
    """Return ``{topic: section_text}`` for the rendered packet."""
    chunks: Dict[str, str] = {}
    matches = list(_SECTION_HEAD_RE.finditer(packet))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(packet)
        chunks[m.group(1)] = packet[m.start():end]
    return chunks


def _bullet_for_table(section: str, table: str) -> Optional[str]:
    """Return the schema-cheat-sheet bullet text for ``table``, or None."""
    for head in _BULLET_HEAD_RE.finditer(section):
        if head.group(1) != table:
            continue
        end_m = _BULLET_END_RE.search(section, head.end())
        end = end_m.start() if end_m else len(section)
        return section[head.start():end]
    return None


def _extract_references(text: str) -> List[Tuple[str, str]]:
    """Return distinct ``(table, column)`` pairs whose table is canonical."""
    seen: set[Tuple[str, str]] = set()
    pairs: List[Tuple[str, str]] = []
    for m in _TABLE_COL_RE.finditer(text):
        table, column = m.group(1), m.group(2)
        if table not in CANONICAL_TABLES:
            continue
        key = (table, column)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def _check_a_for_role(role: str, repo_root: Path, findings: List[str]) -> None:
    """Run Check A for one role; append findings in-place."""
    targets = SKILL_SCAN_TARGETS.get(role, ())
    if not targets:
        return

    packet = render_role_packet(role)
    sections = _section_chunks(packet)
    role_topics = set(ROLE_TOPICS.get(role, ()))

    for rel in targets:
        abs_path = repo_root / rel
        if not abs_path.is_file():
            findings.append(
                f"- SKILL_SCAN_TARGETS contains missing skill path {rel}"
            )
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for table, column in _extract_references(text):
            topic = _TABLE_TOPIC.get(table)
            if topic is None:
                findings.append(
                    f"- role={role} table={table} not in any TOPIC_TABLES topic"
                )
                continue
            if topic not in role_topics:
                findings.append(
                    f"- role={role} references table {table} in topic "
                    f"{topic} not loaded for this role (skill={rel})"
                )
                continue
            section = sections.get(topic)
            if section is None:
                findings.append(
                    f"- role={role} packet missing section for topic "
                    f"{topic} (table {table} referenced by {rel})"
                )
                continue
            bullet = _bullet_for_table(section, table)
            if bullet is None:
                findings.append(
                    f"- role={role} packet missing bullet for table "
                    f"{table} in topic {topic} (referenced by {rel})"
                )
                continue
            if column not in bullet:
                findings.append(
                    f"- role={role} missing column {table}.{column} "
                    f"referenced by {rel}"
                )


def _check_b_envelope(findings: List[str]) -> None:
    """Run Check B (main_agent function-call envelope). Append findings.

    Envelope fields are matched at word boundaries so ``actor_id`` does
    not satisfy the ``actor`` requirement. Function ids are matched as
    plain substrings (the dotted-id form is uniquely shaped). When the
    packet enumerates none of the required function ids, the HC emits
    one finding naming the full expected set.
    """

    packet = render_role_packet("main_agent")
    for field in _ENVELOPE_FIELDS:
        if not re.search(rf"\b{re.escape(field)}\b", packet):
            findings.append(
                f"- role=main_agent envelope field {field!r} missing from packet"
            )
    if not any(fn in packet for fn in REQUIRED_FUNCTION_IDS):
        findings.append(
            "- role=main_agent packet enumerates no REQUIRED_FUNCTION_IDS "
            f"(expected at least one of {list(REQUIRED_FUNCTION_IDS)})"
        )


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more findings")
    return "\n".join(truncated)


def hc_packet_tier_completeness(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-packet-tier-completeness: role packet covers workflow surface."""

    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "repo root not resolvable (skip)")
        return

    findings: List[str] = []
    root = Path(repo_root)
    for role in sorted(ROLE_TOPICS):
        _check_a_for_role(role, root, findings)
    _check_b_envelope(findings)

    if findings:
        rec.record(HC_SLUG, HC_LABEL, "WARN", _format_detail(findings))
    else:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "")


__all__ = [
    "hc_packet_tier_completeness",
    "HC_SLUG",
    "HC_LABEL",
    "SKILL_SCAN_TARGETS",
]
