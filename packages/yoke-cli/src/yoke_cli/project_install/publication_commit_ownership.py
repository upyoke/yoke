"""Prove a local commit is the installer's before publication replaces it.

Publication may move the branch onto an advanced remote and regenerate on
top, which replaces the commits the branch carried. That is only ever safe
for commits the INSTALLER wrote: an operator's commit must be reported, never
discarded, and never published on their behalf.

A matching commit subject is not proof. The installer's message is a fixed
prefix anyone can type, so a commit titled like an install but carrying a
person's own work would, on subject alone, be eligible for replacement.

The commit THIS RUN made is proven by identity: publication holds the sha its
own commit step returned, and a commit that is that sha needs no inference at
all. Every other commit the remote lacks must earn it positively, from the
paths it touched: the subject must match AND every path must be one the
install is sole author of, or a co-owned file the install can show it stayed
inside. Where it cannot be shown — a foreign subject, a path outside
installer territory, a file whose two authors are merged together, or a diff
git could not read — the commit is unproven, and unproven means the caller
refuses to reconcile automatically rather than deciding in the dark.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install import installed_output_paths

NOT_AN_INSTALLER_COMMIT = "not an installer commit"
PATHS_UNREADABLE = "its changed paths could not be read"
_MAX_NAMED_PATHS = 3
_PARENT_PRESENT = "present"
_PARENT_ABSENT = "absent"
_PARENT_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class InstallerTerritory:
    """What the install owns, split by how much of a file that is.

    ``whole_files`` the install writes end to end. ``managed_regions`` it
    co-owns with the operator through a marked block: one delimited region is
    the install's and every line around it is theirs, so a change there is
    only the install's when the text outside the block is untouched.
    ``shared_files`` it co-owns with no such boundary — hook settings whose
    JSON subtree holds both authors' entries, an ignore file it appends a
    line to, the file-line policy config — where nothing cheap tells its
    content from theirs, so a commit touching one is never proven by
    comparison.

    ``own_commits`` are the shas this run's own commit step produced. Those
    need no inference: publication made them from the report it just
    generated, which is why an ordinary install still publishes the shared
    files it legitimately merged into.
    """

    whole_files: frozenset[str] = frozenset()
    managed_regions: frozenset[str] = frozenset()
    shared_files: frozenset[str] = frozenset()
    own_commits: frozenset[str] = frozenset()

    def with_own_commit(self, sha: str | None) -> "InstallerTerritory":
        """The same territory, also owning a commit this run just made."""
        if not sha:
            return self
        return InstallerTerritory(
            whole_files=self.whole_files,
            managed_regions=self.managed_regions,
            shared_files=self.shared_files,
            own_commits=self.own_commits | {str(sha)},
        )


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
    repo_root: Path,
    report: Mapping[str, Any] | None = None,
    *,
    own_commits: Iterable[str] = (),
) -> InstallerTerritory:
    """What the install on disk, plus this run, claims — and how strongly.

    The three path families are built disjoint, narrowest claim last: a file
    both a whole-file section and a co-owned family name is co-owned, because
    the weaker claim is the true one and treating it as whole-file is exactly
    the reading that would authorize discarding an operator edit.
    """
    manifest = files_layer.load_manifest(repo_root)
    regions = frozenset(
        installed_output_paths.managed_region_paths(manifest, report)
    )
    shared = frozenset(
        installed_output_paths.shared_paths(manifest, report)
    ) - regions
    whole = (
        frozenset(installed_output_paths.manifest_owned_paths(manifest))
        | frozenset(installed_output_paths.owned_paths(report))
    ) - regions - shared
    return InstallerTerritory(
        whole_files=whole,
        managed_regions=regions,
        shared_files=shared,
        own_commits=frozenset(str(sha) for sha in own_commits if sha),
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
    if commit.sha in territory.own_commits:
        return ""
    if not checkout_gate.is_installer_commit_message(commit.subject):
        return NOT_AN_INSTALLER_COMMIT
    if not commit.paths_read:
        return PATHS_UNREADABLE
    foreign: list[str] = []
    operator_text: list[str] = []
    shared: list[str] = []
    for path in commit.changed_paths:
        if path in territory.shared_files:
            shared.append(path)
            continue
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
    if shared:
        return (
            "it changes files the install shares with the operator, where "
            "its own entries cannot be told from theirs "
            f"({_named(sorted(shared))})"
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
    before, parent = _parent_text(repo_root, sha, path)
    if parent == _PARENT_UNREADABLE:
        return True
    return _operator_text(before) != _operator_text(after)


def _parent_text(repo_root: Path, sha: str, path: str) -> tuple[str, str]:
    """The file's text before this commit, and how that reading ended.

    Genuine absence and an unreadable parent are the same failed blob read,
    and they are opposite answers: absence means the commit created the file
    and the operator had no text in it, while an unreadable parent means the
    comparison could not be performed at all. Reading them as one would let
    any git failure present itself as "there was nothing here before" and
    clear the way for a destructive reconcile, so the tree is asked directly
    — a commit with no parent had nothing before it, a listed path is read,
    an unlisted one was absent, and a listing that itself fails is the
    refusal.
    """
    parent = checkout_gate.run_git(repo_root, "rev-parse", "--verify", f"{sha}^")
    if parent.returncode != 0:
        return "", _PARENT_ABSENT
    listed = checkout_gate.run_git(
        repo_root, "ls-tree", "--name-only", f"{sha}^", "--", path,
    )
    if listed.returncode != 0:
        return "", _PARENT_UNREADABLE
    if not listed.stdout.strip():
        return "", _PARENT_ABSENT
    before, read = _blob(repo_root, f"{sha}^:{path}")
    return (before, _PARENT_PRESENT) if read else ("", _PARENT_UNREADABLE)


def _operator_text(text: str) -> str:
    """The file with the managed block removed, edge whitespace normalized.

    Inserting the block into a file that already had prose, or stripping it
    back out, moves the operator's text against the file edges without
    changing a word of it — so a byte comparison would read the install's
    own first commit as an operator edit and refuse to publish it. Trimming
    only the outer whitespace keeps every interior change visible, which is
    where an actual edit to their prose shows up.
    """
    from yoke_contracts.project_contract.managed_block import block_span

    span = block_span(text)
    if span is None:
        return text.strip()
    start, end = span
    return (text[:start] + text[end:]).strip()


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
