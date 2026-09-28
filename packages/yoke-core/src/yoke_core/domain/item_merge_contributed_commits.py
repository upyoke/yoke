"""The exact commits one item's landing contributed to its target branch.

A release reads its target's first-parent history, and every commit on that
line needs an owner. The receipt's implementation and merge commits name only
the two ends of a landing, which is not enough: a branch that landed by fast
forward puts every one of its commits on the target's first-parent line, and a
release carrying that landing sees all of them.

The item's contribution is its own first-parent line from the landed commit
back to what the target already held. Walking first parents only is what
keeps a branch sync out of it: ``merge origin/main into <branch>`` records the
branch as its first parent and the synced work as its second, so the synced
commits — already on the target, or belonging to whoever else authored them —
are never walked. Merge commits the item made on its own line, sync merges
included, are the item's.

Two moments can answer it. Before the merge, what the target already holds is
the target itself, so the walk excludes it directly
(:func:`before_landing`). After the merge, a fast forward leaves nothing
behind that says where the target stood, so only a landing that produced a
merge commit can still be answered — its other parent is the target's side
(:func:`after_landing`). That is why the merge boundary records the set before
it merges, and the later writes only ever fill in what that earlier write
could not.
"""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain import standalone_item_merge_git as git


def _first_parent_line(
    repo_root: str, commit_sha: str, exclude: Sequence[str],
) -> tuple[str, ...]:
    """``commit_sha``'s first-parent line down to what ``exclude`` holds."""
    refs = [ref for ref in exclude if ref]
    if not repo_root or not commit_sha or not refs:
        return ()
    listing = git.git_out(
        repo_root, "rev-list", "--first-parent", commit_sha, "--not", *refs,
    )
    return tuple(line.strip() for line in listing.splitlines() if line.strip())


def before_landing(
    repo_root: str, *, target: str, commit_sha: str,
) -> tuple[str, ...]:
    """What ``commit_sha`` will contribute when it lands on ``target``.

    Asked before the merge runs, so the target — local and remote, whichever
    is further along — is exactly what the landing does not contribute.
    """
    if not repo_root:
        return ()
    exclude = [target]
    remote = f"origin/{target}"
    if git.git_out(repo_root, "rev-parse", "--verify", "--quiet", remote):
        exclude.append(remote)
    return _first_parent_line(repo_root, commit_sha, exclude)


def after_landing(
    repo_root: str, *, commit_sha: str, merge_sha: str,
) -> tuple[str, ...]:
    """What ``commit_sha`` contributed through the landing ``merge_sha``.

    Only a merge commit containing ``commit_sha`` can answer: the parents on
    ``commit_sha``'s own line are the item's side, and every other parent is
    what the target — or a synced branch — already held. A true landing merge
    (target first, branch second) and a sync merge that was then fast-forwarded
    (branch first, target second) both resolve this way. A fast forward with
    no merge, or a squash, leaves no such boundary and answers nothing; the
    set recorded before the merge stands for those.
    """
    if not repo_root or not commit_sha or not merge_sha or commit_sha == merge_sha:
        return ()
    parents = git.git_out(repo_root, "rev-list", "-1", "--parents", merge_sha).split()
    if len(parents) < 3 or not git.is_ancestor(repo_root, commit_sha, merge_sha):
        return ()
    others = [
        parent for parent in parents[1:]
        if not git.is_ancestor(repo_root, commit_sha, parent)
    ]
    if len(others) == len(parents) - 1:
        return ()
    return _first_parent_line(repo_root, commit_sha, others)


__all__ = ["after_landing", "before_landing"]
