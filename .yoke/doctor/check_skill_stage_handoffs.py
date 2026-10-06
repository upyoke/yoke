"""Stage handoffs come from the item's next_skill_id, not a copied slash command.

Descriptions and command catalogs are not handoffs. Same-skill re-entry and
internal invocations that explicitly read and follow the target SKILL.md are
allowed. Operator instructions and printed handoffs must use the fresh item
projection; see .agents/skills/yoke/shared/stage-handoff.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain.workflow_definition_builders import REGISTERED_WORKFLOW_SKILL_IDS
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)
from yoke_project_checks._declare import self_project_checks

HC_SLUG = "HC-skill-stage-handoffs"
HC_LABEL = "Skill operator handoffs use the item's next bound skill"
SKILL_ROOT = Path(".agents/skills/yoke")
_COMMAND = re.compile(r"/yoke\s+([a-z][a-z-]*)\b")
_DIRECTIVE = re.compile(
    r"(?<![-\w])(?:run(?:ning)?|re-run|rerun|use(?:s)?|invoke|start|continue|resume|"
    r"next(?=\s*[:`])|next\s+(?:step|skill|bound\s+skill)|"
    r"hand(?:ing|s)?\s*off|handoff|"
    r"route(?:s|d)?\b[^.!?]*\bto|repair\b[^.!?]*\bthrough)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(?:do\s+not|does\s+not|don't|never|must\s+not|cannot|not\s+to)\s+"
    r"(?:(?:print|advertise|announce|explicitly)\s+)?"
    r"(?:run|use|invoke|start|continue|resume|print|advertise|announce|next\s+step|hand\s*off)\b",
    re.IGNORECASE,
)
_BARE_COMMAND = re.compile(r"^\s*[>`'\"]*\s*/yoke\s+[a-z-]+(?:\s+[^\n]*)?$")


def _internal_invocation(block: str, skill: str) -> bool:
    """An internal call names both the procedure and how this agent executes it."""
    return (
        bool(re.search(r"\b(?:read(?:ing)?|follow(?:ing)?)\b", block, re.IGNORECASE))
        and bool(
            re.search(r"\b(?:invoke|dispatch|delegate|call)\b", block, re.IGNORECASE)
        )
        and f"{skill}/SKILL.md" in block
        and not re.search(
            r"\boperator\b|\bnext\s+step\b|\bhand\s*off\b", block, re.IGNORECASE
        )
    )


def scan_handoffs(repo_root: Path) -> list[str]:
    """Find operator directives, including quoted output and wrapped paragraphs."""
    findings = []
    root = repo_root / SKILL_ROOT
    for path in sorted(root.rglob("*.md")):
        owner = path.relative_to(root).parts[0]
        text = path.read_text(encoding="utf-8")
        offset = 0
        for index, block in enumerate(re.split(r"(\n\s*\n)", text)):
            if index % 2:
                offset += len(block)
                continue
            for match in _COMMAND.finditer(block):
                skill = match.group(1)
                if skill == owner or skill not in REGISTERED_WORKFLOW_SKILL_IDS:
                    continue
                if _internal_invocation(block, skill):
                    continue
                line_start = block.rfind("\n", 0, match.start()) + 1
                line_end = block.find("\n", match.end())
                line = block[line_start : line_end if line_end >= 0 else len(block)]
                before = block[: match.start()]
                # A list entry/catalog row is independent of earlier entries.
                if re.match(r"\s*(?:[-*]|\d+\.)\s", line):
                    before = block[line_start : match.start()]
                elif previous := list(_COMMAND.finditer(before)):
                    previous_line_end = before.find("\n", previous[-1].end())
                    if previous_line_end >= 0:
                        before = before[previous_line_end + 1 :]
                # Sentence boundaries prevent a preceding description of a run
                # from turning an unrelated capability reference into a directive.
                sentence = re.split(r"[.!?](?:\s|$)", before)[-1][-120:]
                after = line[line.find(match.group(0)) + len(match.group(0)) :]
                directive = _DIRECTIVE.search(sentence) or re.match(
                    r"(?:\s+\$?[A-Z_{}-]+)?[`'\"\s]*handoff\b", after
                )
                trailing = line[line.find(match.group(0)) + len(match.group(0)) :]
                catalogue = len(re.findall(r"\b[a-z]{2,}\b", trailing)) >= 3
                bare = (
                    _BARE_COMMAND.fullmatch(line) and "```" in block and not catalogue
                )
                descriptive = re.search(r"\brun by\s*$", sentence, re.IGNORECASE)
                descriptive = descriptive or re.match(
                    r"\s*[A-Z][a-z]+s use\b", sentence
                )
                negative_list = re.match(r"[^\n]*\b(?:does|do|must)\s+NOT:\s*", block)
                if (
                    descriptive
                    or negative_list
                    or _NEGATIVE.search(sentence)
                    or not (directive or bare)
                ):
                    continue
                lineno = text[: offset + match.start()].count("\n") + 1
                findings.append(
                    f"{path.relative_to(repo_root)}:{lineno}: hardcoded stage "
                    f"handoff /yoke {skill}; read yoke items detail get ITEM --json "
                    "and render result.item.workflow.next_skill_id. For an internal "
                    "invocation, explicitly read and follow the target SKILL.md."
                )
            offset += len(block)
    return findings


def hc_skill_stage_handoffs(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Skill operator handoffs use the item's next bound skill."""
    repo_root = _resolve_repo_root()
    if not repo_root or not (Path(repo_root) / SKILL_ROOT).is_dir():
        rec.record(HC_SLUG, HC_LABEL, NOT_APPLICABLE, "skill corpus is unavailable")
        return
    findings = scan_handoffs(Path(repo_root))
    rec.record(
        HC_SLUG,
        HC_LABEL,
        "FAIL" if findings else "PASS",
        "\n".join(findings) if findings else "No hardcoded operator stage handoffs.",
    )


PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG.removeprefix("HC-"), HC_LABEL, hc_skill_stage_handoffs),
)
