"""Name the working tree one Pulumi operation renders, and refuse a stray one.

Pulumi programs are rendered from ``<checkout>/infra`` of the project's
registered checkout, which is not always the tree the operator is standing
in: a linked worktree carries no project binding of its own, so a caller
inside one resolves to the registered checkout instead. A resource summary
computed from a tree the caller never named reads exactly like a correct
one, so every run states its source, and a caller standing in a sibling
tree of the same repository is refused before any summary is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TextIO

from yoke_core.domain.pack_pulumi_sources import PULUMI_PROGRAM_SUBDIRECTORY
from yoke_core.tools.pulumi_exec_types import PulumiExecError


#: Revision prefix length carried in operator-facing attribution.
SHORT_REVISION_LENGTH = 12

_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class RenderSource:
    """The tree a Pulumi operation reads its program files from."""

    checkout: Path
    #: Absolute git object store shared by every worktree of one repository,
    #: or empty when the checkout is not under git at all.
    repository: str
    #: Committed revision of ``checkout``, or empty when there is none.
    revision: str
    #: Entries changed under the rendered program directory.
    uncommitted: int

    @property
    def tree_state(self) -> str:
        """Whether the rendered directory adds anything beyond the revision."""
        if not self.uncommitted:
            return f"{PULUMI_PROGRAM_SUBDIRECTORY}/ clean"
        return (
            f"{self.uncommitted} uncommitted change(s) "
            f"in {PULUMI_PROGRAM_SUBDIRECTORY}/"
        )

    @property
    def description(self) -> str:
        """Checkout plus revision, precise enough to reproduce the render."""
        if not self.repository:
            return f"{self.checkout} (not a git checkout; revision unavailable)"
        if not self.revision:
            return f"{self.checkout} (no commit yet; {self.tree_state})"
        revision = self.revision[:SHORT_REVISION_LENGTH]
        return f"{self.checkout} @ {revision} ({self.tree_state})"


def resolve_render_source(checkout: Path) -> RenderSource:
    """Describe the tree whose program files a Pulumi operation will render."""
    root = Path(checkout).expanduser().resolve()
    repository = _repository_of(root)
    if not repository:
        return RenderSource(
            checkout=root, repository="", revision="", uncommitted=0
        )
    changed = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
        "--",
        PULUMI_PROGRAM_SUBDIRECTORY,
    )
    return RenderSource(
        checkout=root,
        repository=repository,
        revision=_git(root, "rev-parse", "HEAD"),
        uncommitted=len([line for line in changed.splitlines() if line.strip()]),
    )


def announce_render_source(
    checkout: Path,
    *,
    caller_root: Path | None,
    err: TextIO,
) -> RenderSource:
    """Refuse a stray working tree, then state the source that will render.

    ``caller_root`` is the git top-level the operator invoked from, or
    ``None`` when they are not inside a working tree at all — a caller
    standing nowhere contradicts nothing, so only the attribution applies.
    """
    source = resolve_render_source(checkout)
    _assert_caller_tree(source, caller_root)
    err.write(f"yoke pulumi exec: rendering {source.description}\n")
    err.flush()
    return source


def _assert_caller_tree(source: RenderSource, caller_root: Path | None) -> None:
    """Refuse when the caller stands in a sibling tree of the same repository.

    A caller in an unrelated repository is working across projects on
    purpose and is left alone; only a second working tree of the very
    repository being rendered can be mistaken for the one that rendered.
    """
    if caller_root is None or not source.repository:
        return
    caller = Path(caller_root).expanduser().resolve()
    if caller == source.checkout:
        return
    if _repository_of(caller) != source.repository:
        return
    raise PulumiExecError(
        f"yoke pulumi exec renders {source.description}, but this command ran "
        f"from {caller} — the same repository, a different working tree. "
        "Refusing rather than reporting a resource summary for a tree you did "
        f"not ask about. Run from {source.checkout}, or bind this working tree "
        f"with `yoke project register {caller} --project-id <id>`."
    )


def _repository_of(root: Path) -> str:
    """Return the absolute shared git directory, or empty when there is none."""
    common = _git(root, "rev-parse", "--git-common-dir")
    if not common:
        return ""
    resolved = Path(common)
    if not resolved.is_absolute():
        resolved = root / resolved
    return str(resolved.resolve())


def _git(root: Path, *args: str) -> str:
    """Read one git fact, treating any failure as an unavailable answer."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode:
        return ""
    return result.stdout.strip()


__all__ = [
    "RenderSource",
    "SHORT_REVISION_LENGTH",
    "announce_render_source",
    "resolve_render_source",
]
