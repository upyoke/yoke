"""Read a file as one commit's parent held it, or say the read failed.

The ownership proof for a co-owned file compares the operator's text
before and after a commit, so it needs the "before" — and needs to know
when there is honestly none versus when git could not tell it. Those two
arrive as the same failed read and mean opposite things: nothing existed
to change clears the commit, while an unperformed comparison must refuse
it. Every step here therefore answers with one of three named states
rather than an empty string.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.project_install import checkout_gate

PRESENT = "present"
ABSENT = "absent"
UNREADABLE = "unreadable"


def parent_text(repo_root: Path, sha: str, path: str) -> tuple[str, str]:
    """The file's text before this commit, and how that reading ended.

    Genuine absence and an unreadable parent arrive as the same failed read,
    and they are opposite answers: absence means the commit created the file
    and the operator had no text in it, while unreadable means the comparison
    could not be performed at all. Reading them as one lets any git failure
    present itself as "there was nothing here before" and clear the way for a
    destructive reconcile, so nothing is inferred from a failure at either
    step.

    Only the commit's OWN header proves it has no parent. Resolving ``<sha>^``
    fails for a root commit and for a parent that is merely unavailable
    alike, so the header is read instead: no recorded parent is a root commit
    and genuinely had nothing before it, while a recorded parent this
    repository cannot read is a refusal. Past that, the parent's tree answers
    directly — a listed path is read, an unlisted one was absent, and a
    listing or blob read that fails is the refusal again.
    """
    parents, header_read = recorded_parents(repo_root, sha)
    if not header_read:
        return "", UNREADABLE
    if not parents:
        return "", ABSENT
    parent = parents[0]
    listed = checkout_gate.run_git(
        repo_root, "ls-tree", "--name-only", parent, "--", path,
    )
    if listed.returncode != 0:
        return "", UNREADABLE
    if not listed.stdout.strip():
        return "", ABSENT
    before, read = blob(repo_root, f"{parent}:{path}")
    return (before, PRESENT) if read else ("", UNREADABLE)


def recorded_parents(repo_root: Path, sha: str) -> tuple[tuple[str, ...], bool]:
    """The parents this commit records, and whether its header was read.

    The commit object carries its own parent list, so this distinguishes
    "records no parent" — the one fact that proves a root commit — from
    "its parent could not be resolved", which proves nothing. The header
    ends at the first blank line, so a commit message that happens to begin
    a line with ``parent`` is never read as one.
    """
    shown = checkout_gate.run_git(repo_root, "cat-file", "commit", sha)
    if shown.returncode != 0:
        return (), False
    parents: list[str] = []
    for line in shown.stdout.splitlines():
        if not line.strip():
            break
        field, _, value = line.partition(" ")
        if field == "parent" and value.strip():
            parents.append(value.strip())
    return tuple(parents), True


def blob(repo_root: Path, revision_path: str) -> tuple[str, bool]:
    shown = checkout_gate.run_git(repo_root, "show", revision_path)
    if shown.returncode != 0:
        return "", False
    return shown.stdout, True


__all__ = [
    "ABSENT",
    "PRESENT",
    "UNREADABLE",
    "blob",
    "parent_text",
    "recorded_parents",
]
