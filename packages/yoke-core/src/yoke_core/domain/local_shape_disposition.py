"""Disposition guard for retired repo-local ``data/**`` and ``projects/**``.

local-authority cleanup removes repo-root ``data/`` and ``projects/`` as live tracked
surfaces. This module audits the current git index and fails whenever a
tracked path remains under either root.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from yoke_core.api.repo_root import find_repo_root


LOCAL_SHAPE_ROOTS = ("data", "projects")

BUCKET_UNCLASSIFIED = "unclassified"


class LocalShapeDispositionError(Exception):
    """Raised when repo-local shape disposition coverage fails."""


@dataclass(frozen=True)
class DispositionRule:
    """One explicit tracked-path disposition rule."""

    path: str
    match: str
    bucket: str
    disposition: str
    rationale: str
    integration_note: str = ""

    def matches(self, tracked_path: str) -> bool:
        if self.match == "exact":
            return tracked_path == self.path
        if self.match == "prefix":
            return tracked_path == self.path or tracked_path.startswith(
                f"{self.path}/"
            )
        raise LocalShapeDispositionError(
            f"unknown local-shape rule match type: {self.match}"
        )


@dataclass(frozen=True)
class DispositionEntry:
    """Disposition outcome for one tracked path."""

    path: str
    bucket: str
    disposition: str
    rule_path: str
    rationale: str
    integration_note: str = ""

    @property
    def is_unclassified(self) -> bool:
        return self.bucket == BUCKET_UNCLASSIFIED


@dataclass(frozen=True)
class DispositionReport:
    """Complete local-shape audit result."""

    entries: tuple[DispositionEntry, ...]

    @property
    def unclassified(self) -> tuple[DispositionEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_unclassified)

    @property
    def has_unclassified(self) -> bool:
        return bool(self.unclassified)

    def bucket_counts(self) -> dict[str, int]:
        counts = Counter(entry.bucket for entry in self.entries)
        return dict(sorted(counts.items()))


DEFAULT_DISPOSITION_RULES: tuple[DispositionRule, ...] = ()


def list_tracked_local_shape_paths(repo_root: Path) -> tuple[str, ...]:
    """Return sorted git-tracked paths under ``data/**`` and ``projects/**``."""

    root = Path(repo_root).resolve()
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", *LOCAL_SHAPE_ROOTS],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise LocalShapeDispositionError(
            f"could not list tracked local-shape paths{detail}"
        )
    return tuple(
        sorted(
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        )
    )


def audit_local_shape_disposition(
    repo_root: Path | None = None,
    *,
    tracked_paths: Sequence[str] | None = None,
    rules: Sequence[DispositionRule] = DEFAULT_DISPOSITION_RULES,
) -> DispositionReport:
    """Classify tracked repo-local retired-shape paths.

    Passing ``tracked_paths`` lets tests and integration simulations exercise
    the policy without creating a temporary git repository.
    """

    if tracked_paths is None:
        if repo_root is None:
            repo_root = find_repo_root(Path(__file__))
        tracked_paths = list_tracked_local_shape_paths(Path(repo_root))

    entries = tuple(
        _classify_path(path, rules)
        for path in sorted(_normalise_tracked_paths(tracked_paths))
    )
    return DispositionReport(entries=entries)


def assert_explicit_local_shape_disposition(
    repo_root: Path | None = None,
    *,
    tracked_paths: Sequence[str] | None = None,
    rules: Sequence[DispositionRule] = DEFAULT_DISPOSITION_RULES,
) -> DispositionReport:
    """Return the report or raise if any tracked data/projects path remains."""

    report = audit_local_shape_disposition(
        repo_root,
        tracked_paths=tracked_paths,
        rules=rules,
    )
    if report.has_unclassified:
        paths = "\n".join(f"- {entry.path}" for entry in report.unclassified)
        raise LocalShapeDispositionError(
            "tracked data/** or projects/** paths remain after local-authority cleanup:\n"
            f"{paths}"
        )
    return report


def render_local_shape_disposition_report(report: DispositionReport) -> str:
    """Render a deterministic Markdown disposition report."""

    lines = [
        "# Repo-Local Shape Disposition",
        "",
        "## Summary",
        "",
    ]
    counts = report.bucket_counts()
    if counts:
        for bucket, count in counts.items():
            lines.append(f"- {bucket}: {count}")
    else:
        lines.append("- no tracked data/** or projects/** paths")

    lines.extend(
        [
            "",
            "## Entries",
            "",
            "| Path | Bucket | Disposition | Rule | Integration Note |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for entry in report.entries:
        note = entry.integration_note or ""
        lines.append(
            "| "
            f"{entry.path} | "
            f"{entry.bucket} | "
            f"{entry.disposition} | "
            f"{entry.rule_path} | "
            f"{note} |"
        )
    return "\n".join(lines) + "\n"


def _normalise_tracked_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalised: list[str] = []
    for path in paths:
        cleaned = path.strip().replace("\\", "/")
        if not cleaned:
            continue
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if cleaned.startswith(f"{LOCAL_SHAPE_ROOTS[0]}/") or cleaned.startswith(
            f"{LOCAL_SHAPE_ROOTS[1]}/"
        ):
            normalised.append(cleaned)
    return tuple(normalised)


def _classify_path(
    tracked_path: str,
    rules: Sequence[DispositionRule],
) -> DispositionEntry:
    for rule in rules:
        if rule.matches(tracked_path):
            return DispositionEntry(
                path=tracked_path,
                bucket=rule.bucket,
                disposition=rule.disposition,
                rule_path=rule.path,
                rationale=rule.rationale,
                integration_note=rule.integration_note,
            )
    return DispositionEntry(
        path=tracked_path,
        bucket=BUCKET_UNCLASSIFIED,
        disposition=BUCKET_UNCLASSIFIED,
        rule_path="",
        rationale=(
            "Tracked repo-local data/projects path is not allowed after "
            "local-authority cleanup."
        ),
    )
