"""Prove a local commit is the installer's before publication replaces it.

Publication may move the branch onto an advanced remote and regenerate on
top, which replaces the commits the branch carried. That is only ever safe
for commits the INSTALLER wrote: an operator's commit must be reported, never
discarded, and never published on their behalf.

A matching commit subject is not proof. The installer's message is a fixed
prefix anyone can type, so a commit titled like an install but carrying a
person's own work would, on subject alone, be eligible for replacement. Proof
here is positive and path-based: the subject must match AND every path the
commit touched must be one the install already records as its own. Anything
else — a foreign subject, a path outside installer territory, or a diff git
could not read — is unproven, and unproven means the caller refuses to
reconcile automatically rather than deciding in the dark.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import installed_output_paths

NOT_AN_INSTALLER_COMMIT = "not an installer commit"
PATHS_UNREADABLE = "its changed paths could not be read"
_MAX_NAMED_PATHS = 3


@dataclass(frozen=True)
class LocalCommit:
    """One commit the remote lacks, with the paths it changed."""

    sha: str
    subject: str
    changed_paths: tuple[str, ...] = ()
    paths_read: bool = True

    @property
    def label(self) -> str:
        return f"{self.sha[:12]} {self.subject}"


def installer_owned_paths(
    repo_root: Path, report: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    """Every repo path the install on disk, plus this run, claims as its own."""
    recorded = installed_output_paths.manifest_owned_paths(
        files_layer.load_manifest(repo_root)
    )
    return frozenset(recorded) | frozenset(
        installed_output_paths.owned_paths(report)
    )


def read_local_only_commits(
    repo_root: Path, remote_sha: str, local_sha: str,
) -> tuple[tuple[LocalCommit, ...], bool, str]:
    """Read the commits the remote lacks, or report that the read failed.

    An unreadable log is not an empty one. Returning no commits there would
    read as "the operator owns nothing here", which is exactly the answer
    that permits replacing their work, so the failure is carried instead.
    """
    listed = checkout_gate.run_git(
        repo_root, "log", "--format=%H%x00%s", f"{remote_sha}..{local_sha}",
    )
    if listed.returncode != 0:
        detail = (
            listed.stderr.strip()
            or listed.stdout.strip()
            or "git log failed with no diagnostic"
        )
        return (), False, f"could not read the commits {remote_sha[:12]} lacks: {detail}"
    commits: list[LocalCommit] = []
    for line in listed.stdout.splitlines():
        sha, _, subject = line.partition("\0")
        if not sha.strip():
            continue
        changed, read = _changed_paths(repo_root, sha.strip())
        commits.append(
            LocalCommit(
                sha=sha.strip(),
                subject=subject.strip(),
                changed_paths=changed,
                paths_read=read,
            )
        )
    return tuple(commits), True, ""


def _changed_paths(repo_root: Path, sha: str) -> tuple[tuple[str, ...], bool]:
    """Every repo-relative path one commit changed, and whether git said so."""
    listed = checkout_gate.run_git(
        repo_root, "show", "--name-only", "--format=", "--no-renames", sha,
    )
    if listed.returncode != 0:
        return (), False
    return tuple(
        line.strip() for line in listed.stdout.splitlines() if line.strip()
    ), True


def unproven_commits(
    commits: tuple[LocalCommit, ...], owned: frozenset[str],
) -> tuple[str, ...]:
    """Name every commit publication may not treat as its own, with why."""
    unproven: list[str] = []
    for commit in commits:
        reason = _unproven_reason(commit, owned)
        if reason:
            unproven.append(f"{commit.label} — {reason}")
    return tuple(unproven)


def _unproven_reason(commit: LocalCommit, owned: frozenset[str]) -> str:
    if not checkout_gate.is_installer_commit_message(commit.subject):
        return NOT_AN_INSTALLER_COMMIT
    if not commit.paths_read:
        return PATHS_UNREADABLE
    outside = sorted(path for path in commit.changed_paths if path not in owned)
    if not outside:
        return ""
    named = ", ".join(outside[:_MAX_NAMED_PATHS])
    if len(outside) > _MAX_NAMED_PATHS:
        named = f"{named}, and {len(outside) - _MAX_NAMED_PATHS} more"
    return f"it changes paths the install does not own ({named})"


__all__ = [
    "NOT_AN_INSTALLER_COMMIT",
    "read_local_only_commits",
    "PATHS_UNREADABLE",
    "LocalCommit",
    "installer_owned_paths",
    "unproven_commits",
]
