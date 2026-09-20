"""Git merge history as landing facts a backfill can insert.

Live close-out records landings as they happen. The merges that predate
that writer are still in git, and every column of a landing derives from
one ``git log --merges`` walk: the merge commit, its second parent, the
pull-request number and item sequence in the branch name, the first-parent
branch, and the committer time.

A reconstructed ``landed_at`` is that committer time. For a merge-queue
landing the queue creates the merge commit when the train forms and merges
it minutes later, so git runs minutes early of the GitHub-observed moment
close-out would have stored. Rows carry ``origin='reconstructed'`` so a
reader can tell.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from yoke_core.domain.item_merge_provenance_operator import MERGED_AT_FORMAT

#: Field separator inside one ``git log`` record.
_UNIT = "\x1f"
#: Record separator ahead of each merge commit.
_RECORD = "\x1e"
_LOG_FORMAT = f"{_RECORD}%H{_UNIT}%P{_UNIT}%ct{_UNIT}%s"

_PR_NUMBER = re.compile(r"Merge pull request #(\d+)", re.IGNORECASE)
_FROM_YOK_BRANCH = re.compile(
    r"\bfrom\s+\S+/(YOK-\d+)",
    re.IGNORECASE,
)
_MERGE_YOK_BRANCH = re.compile(
    r"Merge branch '(YOK-\d+)[^']*'",
    re.IGNORECASE,
)
_SEQUENCE = re.compile(r"YOK-(\d+)", re.IGNORECASE)

YOKE_PROJECT_SLUG = "yoke"
DEFAULT_TARGET_BRANCH = "main"
DEFAULT_REVISION = "origin/main"


@dataclass(frozen=True)
class LandingFact:
    """One git-derived landing, not yet resolved to an ``items.id``."""

    merge_sha: str
    candidate_sha: str
    pr_number: str
    target_branch: str
    landed_at: str
    project_sequence: int

    def as_json(self) -> dict[str, object]:
        return {
            "merge_sha": self.merge_sha,
            "candidate_sha": self.candidate_sha,
            "pr_number": self.pr_number,
            "target_branch": self.target_branch,
            "landed_at": self.landed_at,
            "project_sequence": self.project_sequence,
        }


@dataclass(frozen=True)
class MergeWalk:
    """Facts plus the merges git stated that did not name a YOK branch."""

    facts: tuple[LandingFact, ...]
    skipped_unresolved_branch: int


def _git_out(repo_root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_root, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _landed_at(epoch: str) -> str:
    try:
        seconds = int(epoch)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime(MERGED_AT_FORMAT)


def _project_sequence(subject: str) -> int | None:
    """The YOK-N on the merged branch, not any YOK-N mentioned in the title."""
    named = _FROM_YOK_BRANCH.search(subject) or _MERGE_YOK_BRANCH.search(subject)
    if named is None:
        return None
    match = _SEQUENCE.search(named.group(1))
    if match is None:
        return None
    return int(match.group(1))


def _pr_number(subject: str) -> str:
    match = _PR_NUMBER.search(subject)
    return match.group(1) if match else ""


def parse_merge_subject(subject: str) -> tuple[int, str] | None:
    """Return ``(project_sequence, pr_number)`` when the subject names a YOK branch."""
    sequence = _project_sequence(subject)
    if sequence is None:
        return None
    return sequence, _pr_number(subject)


def fact_from_log_fields(
    merge_sha: str,
    parents: str,
    epoch: str,
    subject: str,
    *,
    target_branch: str = DEFAULT_TARGET_BRANCH,
) -> LandingFact | None:
    parsed = parse_merge_subject(subject)
    if parsed is None:
        return None
    sequence, pr_number = parsed
    parent_shas = [part for part in parents.split() if part]
    candidate = parent_shas[1] if len(parent_shas) > 1 else merge_sha
    landed_at = _landed_at(epoch)
    if not merge_sha or not landed_at:
        return None
    return LandingFact(
        merge_sha=merge_sha,
        candidate_sha=candidate,
        pr_number=pr_number,
        target_branch=target_branch,
        landed_at=landed_at,
        project_sequence=sequence,
    )


def walk_merge_history(
    repo_root: str,
    *,
    revision: str = DEFAULT_REVISION,
    target_branch: str = DEFAULT_TARGET_BRANCH,
) -> MergeWalk:
    """Every merge ``revision`` reaches, as facts or an unresolved skip."""
    log = _git_out(repo_root, "log", "--merges", f"--format={_LOG_FORMAT}", revision)
    facts: list[LandingFact] = []
    skipped = 0
    for record in log.split(_RECORD):
        if not record.strip():
            continue
        parts = record.strip("\n").split(_UNIT, 3)
        if len(parts) != 4:
            skipped += 1
            continue
        merge_sha, parents, epoch, subject = parts
        fact = fact_from_log_fields(
            merge_sha.strip(),
            parents,
            epoch.strip(),
            subject.strip(),
            target_branch=target_branch,
        )
        if fact is None:
            skipped += 1
            continue
        facts.append(fact)
    return MergeWalk(facts=tuple(facts), skipped_unresolved_branch=skipped)


def facts_from_json(payload: str | Sequence[object]) -> tuple[LandingFact, ...]:
    rows = json.loads(payload) if isinstance(payload, str) else payload
    facts: list[LandingFact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        facts.append(
            LandingFact(
                merge_sha=str(row["merge_sha"]),
                candidate_sha=str(row.get("candidate_sha") or ""),
                pr_number=str(row.get("pr_number") or ""),
                target_branch=str(row.get("target_branch") or DEFAULT_TARGET_BRANCH),
                landed_at=str(row["landed_at"]),
                project_sequence=int(row["project_sequence"]),
            )
        )
    return tuple(facts)


def facts_to_json(facts: Iterable[LandingFact]) -> str:
    """One-line snapshot so the frozen payload stays inside the file-line limit."""
    return json.dumps([fact.as_json() for fact in facts], separators=(",", ":"))


__all__ = [
    "DEFAULT_REVISION",
    "DEFAULT_TARGET_BRANCH",
    "LandingFact",
    "MergeWalk",
    "YOKE_PROJECT_SLUG",
    "fact_from_log_fields",
    "facts_from_json",
    "facts_to_json",
    "parse_merge_subject",
    "walk_merge_history",
]
