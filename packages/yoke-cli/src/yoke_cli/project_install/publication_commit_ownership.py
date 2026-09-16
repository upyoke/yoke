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
class InstallerTerritory:
    """What the install owns, split by how much of a file that is.

    ``whole_files`` the install writes end to end. ``managed_regions`` it
    co-owns with the operator: one marked block is the install's and every
    line around it is theirs, so a change there is only the install's when
    the text outside the block is untouched.
    """

    whole_files: frozenset[str] = frozenset()
    managed_regions: frozenset[str] = frozenset()


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


def installer_territory(
    repo_root: Path, report: Mapping[str, Any] | None = None,
) -> InstallerTerritory:
    """What the install on disk, plus this run, claims — whole files and regions."""
    manifest = files_layer.load_manifest(repo_root)
    regions = frozenset(
        installed_output_paths.managed_region_paths(manifest, report)
    )
    whole = (
        frozenset(installed_output_paths.manifest_owned_paths(manifest))
        | frozenset(installed_output_paths.owned_paths(report))
    ) - regions
    return InstallerTerritory(whole_files=whole, managed_regions=regions)


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
    commits: tuple[LocalCommit, ...],
    territory: InstallerTerritory,
    *,
    repo_root: Path,
) -> tuple[str, ...]:
    """Name every commit publication may not treat as its own, with why."""
    unproven: list[str] = []
    for commit in commits:
        reason = _unproven_reason(commit, territory, repo_root)
        if reason:
            unproven.append(f"{commit.label} — {reason}")
    return tuple(unproven)


def _unproven_reason(
    commit: LocalCommit, territory: InstallerTerritory, repo_root: Path,
) -> str:
    if not checkout_gate.is_installer_commit_message(commit.subject):
        return NOT_AN_INSTALLER_COMMIT
    if not commit.paths_read:
        return PATHS_UNREADABLE
    foreign: list[str] = []
    operator_text: list[str] = []
    for path in commit.changed_paths:
        if path in territory.whole_files:
            continue
        if path not in territory.managed_regions:
            foreign.append(path)
            continue
        if _changed_outside_block(repo_root, commit.sha, path):
            operator_text.append(path)
    if foreign:
        return (
            "it changes paths the install does not own "
            f"({_named(sorted(foreign))})"
        )
    if operator_text:
        return (
            "it changes the operator's own text outside the managed block "
            f"({_named(sorted(operator_text))})"
        )
    return ""


def _changed_outside_block(repo_root: Path, sha: str, path: str) -> bool:
    """True when this commit altered anything around the managed block.

    The install owns one marked region of a co-owned file, so the proof is a
    comparison of everything else: identical outside the block means the
    commit stayed inside the install's territory. An unreadable result is
    treated as changed, because a proof that cannot be performed is not one.
    """
    after, after_read = _blob(repo_root, f"{sha}:{path}")
    if not after_read:
        return True
    before, before_read = _blob(repo_root, f"{sha}^:{path}")
    if not before_read:
        # The commit created the file; the operator had no text there yet.
        before = ""
    return _outside_block(before) != _outside_block(after)


def _outside_block(text: str) -> str:
    from yoke_contracts.project_contract.managed_block import block_span

    span = block_span(text)
    if span is None:
        return text
    start, end = span
    return text[:start] + text[end:]


def _blob(repo_root: Path, revision_path: str) -> tuple[str, bool]:
    shown = checkout_gate.run_git(repo_root, "show", revision_path)
    if shown.returncode != 0:
        return "", False
    return shown.stdout, True


def _named(paths: list[str]) -> str:
    named = ", ".join(paths[:_MAX_NAMED_PATHS])
    if len(paths) > _MAX_NAMED_PATHS:
        named = f"{named}, and {len(paths) - _MAX_NAMED_PATHS} more"
    return named


__all__ = [
    "NOT_AN_INSTALLER_COMMIT",
    "read_local_only_commits",
    "PATHS_UNREADABLE",
    "InstallerTerritory",
    "LocalCommit",
    "installer_territory",
    "unproven_commits",
]
