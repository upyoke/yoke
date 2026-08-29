"""Git pre-commit hook (hard-fails on file-line-limit violations).

Python owner for the ``.git/hooks/pre-commit`` shim installed by
``yoke project install``. The shim does ``exec yoke git pre-commit``
through the machine-installed launcher, which routes here via
:mod:`yoke_cli.commands.git_hook`; worktrees share the
main repo's ``.git/hooks/`` so this guard protects every worktree
commit automatically.

Behaviour on each commit, in order:

1. **Diverged-files warning (advisory, exits 0).** Emits a WARNING to
   stderr when any staged path also has unstaged working-tree changes,
   signalling that the commit may not match the working tree. This check
   never blocks a commit.
2. **File-line-limit check (hard-fail, exits 1 on violation).** Invokes
   :func:`yoke_core.domain.file_line_check.changed_files_check` in
   ``staged=True`` mode against the staged content. If the verdict
   reports any hard-fail, the hook prints a summary to stderr and
   returns 1, which causes git to abort the commit.
3. **Generated-content checks (hard-fail).** The field-note inline
   renderer, the harness wake-capability renderer, and the harness agent
   renderer each compare their generated outputs against the sources they
   derive from, so a commit cannot pair an edited source with a stale
   rendered artifact. The capability pass additionally refuses a wake claim
   written outside a generated block without naming the manifest fact it
   depends on.

If ``yoke_core.domain.file_line_check`` cannot be imported, the hook
fails closed (returns 1) rather than silently skipping. This is
deliberate: a quality gate that silently disables itself on module
breakage is worse than no gate at all.

Operator escape hatch: ``git commit --no-verify`` bypasses the shim
entirely. This is the documented path when the check is wrong or when
an in-flight refactor temporarily exceeds the limit.

The canonical owner of the 350-line rule and its temporary-exception
list is :mod:`yoke_core.domain.file_line_check`.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import Iterable


def _git_name_only(args: Iterable[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def find_diverged(diverged: Iterable[str], staged: Iterable[str]) -> list[str]:
    """Return the intersection of *diverged* and *staged* file paths."""
    staged_set = set(staged)
    return [path for path in diverged if path in staged_set]


def _format_warning(files: list[str]) -> str:
    lines: list[str] = [
        "WARNING: These staged files have unstaged changes — commit may not match working tree:",
    ]
    for path in files:
        lines.append(f"  {path}")
    lines.append(
        "\nRun 'git add <file>' to stage latest content, "
        "or 'git commit --no-verify' to skip this check."
    )
    return "\n".join(lines) + "\n"


def _emit_diverged_warning() -> None:
    """Run the advisory diverged-files check. Always non-blocking."""
    diverged = _git_name_only(["diff", "--name-only"])
    if not diverged:
        return
    staged = _git_name_only(["diff", "--cached", "--name-only"])
    if not staged:
        return
    warn_files = find_diverged(diverged, staged)
    if not warn_files:
        return
    sys.stderr.write(_format_warning(warn_files))


def _resolve_repo_root() -> str | None:
    """Return the git toplevel path, or None when not in a git tree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _format_file_line_summary(verdict, *, limit: int) -> str:
    """Render the hard-fail summary that git displays before aborting."""
    lines: list[str] = [
        "ERROR: file-line-limit gate blocked this commit.",
        "",
        "Hard fails:",
    ]
    for change in verdict.hard_fails:
        removal = change.new_line_count - limit
        if change.old_line_count == 0:
            detail = "NEW authored file; "
        elif change.old_line_count > limit:
            detail = f"existing {change.old_line_count}-line file grew; "
        else:
            detail = f"grew from {change.old_line_count} lines; "
        detail += (
            f"current {change.new_line_count}, limit {limit}, "
            f"remove {removal} line(s)"
        )
        lines.append(f"  - {change.path}: {detail}")
    lines.append("")
    lines.append(
        "Run `yoke check file-line --staged` to re-inspect."
    )
    lines.append(
        "Split the file into smaller modules, or use "
        "`git commit --no-verify` to bypass."
    )
    return "\n".join(lines) + "\n"


def _run_file_line_check_or_block() -> int:
    """Run the file-line-limit check; return rc to propagate."""
    try:
        from yoke_core.domain import file_line_check
    except ImportError:
        sys.stderr.write(
            "ERROR: file-line-limit checker module not available — "
            "install/repair yoke_core.domain.file_line_check.\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1  # FAIL-CLOSED: missing checker blocks the commit.

    repo_root = _resolve_repo_root()
    if repo_root is None:
        # Not in a git tree somehow — defer (don't block) so non-git
        # contexts work.
        return 0

    verdict = file_line_check.changed_files_check(
        repo_root=pathlib.Path(repo_root),
        staged=True,
    )
    policy = file_line_check.resolved_policy(pathlib.Path(repo_root))
    if verdict.ok:
        return 0

    sys.stderr.write(_format_file_line_summary(verdict, limit=policy.limit))
    return 1


def _run_field_note_render_or_block() -> int:
    """Run the field-note renderer in --check mode; rc to propagate.

    Fail-closed shape matches :func:`_run_file_line_check_or_block`: a
    missing renderer module blocks the commit because a quality gate that
    silently disables itself on import error is worse than no gate.
    """
    try:
        from yoke_core.tools import render_field_note_inline as rri
    except ImportError:
        sys.stderr.write(
            "ERROR: field-note renderer not available — "
            "install/repair yoke_core.tools.render_field_note_inline.\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1

    repo_root = _resolve_repo_root()
    if repo_root is None:
        return 0

    result = rri.render(pathlib.Path(repo_root), check=True)
    if result.ok and not result.changed:
        return 0

    sys.stderr.write(rri._format_drift_summary(result, check=True))
    return 1


def _run_harness_capability_render_or_block() -> int:
    """Refuse commits whose wake capability disagrees with its contract.

    Fail-closed like :func:`_run_field_note_render_or_block`. The scan also
    refuses a wake claim written past the contract, which is what went stale.
    """
    try:
        from yoke_core.tools import harness_continuation_coherence as hcc
        from yoke_core.tools import render_harness_capability_inline as rhc
    except ImportError:
        sys.stderr.write(
            "ERROR: harness capability renderer not available — install/"
            "repair yoke_core.tools.render_harness_capability_inline.\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1

    repo_root = _resolve_repo_root()
    if repo_root is None:
        return 0

    root = pathlib.Path(repo_root)
    result = rhc.render(root, check=True)
    findings = rhc.uncited_capability_claims(root)
    continuations = hcc.continuation_contract_contradictions(root)
    if result.ok and not result.changed and not findings and not continuations:
        return 0

    # Both formatters return "" when they have nothing to report.
    sys.stderr.write(rhc.format_render_drift(result, check=True))
    sys.stderr.write(rhc.format_uncited_summary(findings))
    sys.stderr.write(hcc.format_continuation_summary(continuations))
    return 1


def _run_agent_render_check_or_block() -> int:
    """Refuse commits whose rendered harness adapters disagree with the
    canonical bodies and packet seed they are generated from.

    Without this, an edit to a packet seed commits cleanly alongside
    stale rendered adapters and the mismatch only surfaces in the full
    test suite, long after the commit that caused it. Same shape as
    :func:`_run_field_note_render_or_block`: the renderer is the source
    of truth and the operator re-renders and re-stages.

    Skips silently outside a Yoke source checkout — a project repo has
    no canonical agent bodies to render from. A render that cannot be
    evaluated (unreachable DB, seed import failure) warns without
    blocking: an unverifiable gate must not brick unrelated commits.
    """
    try:
        from yoke_core.domain import agents_render
    except ImportError:
        sys.stderr.write(
            "ERROR: agent renderer not available — "
            "install/repair yoke_core.domain.agents_render.\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1

    repo_root = _resolve_repo_root()
    if repo_root is None:
        return 0
    root = pathlib.Path(repo_root)
    if not (root / agents_render.CANONICAL_DIR).is_dir():
        return 0

    drifted = agents_render.detect_substrate_drift(target_root=root)
    if not drifted:
        return 0
    blocking = [d for d in drifted if not d.startswith("render-error:")]
    if not blocking:
        sys.stderr.write(
            "WARNING: agent render drift could not be evaluated:\n"
            + "".join(f"  {entry}\n" for entry in drifted)
        )
        return 0
    sys.stderr.write(
        "ERROR: rendered harness adapters disagree with their canonical "
        "sources:\n"
        + "".join(f"  {entry}\n" for entry in drifted)
        + "Run `yoke agents render` and re-stage the rendered files.\n"
        "Use `git commit --no-verify` to bypass this check.\n"
    )
    return 1


def _run_worktree_status_check_or_block() -> int:
    """Refuse commits on a YOK-N worktree branch when the item's status
    isn't in the implementation-phase set. Skips silently for non-item
    branches and unreachable DBs."""
    try:
        from yoke_core.domain import check_worktree_status_invariant
    except ImportError:
        # Fail open on missing module — file_line_check is the primary
        # gate, and silently disabling this advisory check is safer
        # than blocking commits on a tooling regression.
        return 0
    verdict = check_worktree_status_invariant.evaluate()
    if verdict.ok:
        return 0
    sys.stderr.write(verdict.message)
    return 1


def _run_path_claim_coverage_check_or_block() -> int:
    """Refuse worktree commits when staged files exceed the active
    path-claim coverage. No-op outside a worktree, when no current item
    resolves, when the item has no non-terminal claim, or when the
    suppression token is in the commit message body."""
    try:
        from yoke_core.domain import check_path_claim_coverage_at_commit
    except ImportError:
        # Fail open on missing module — silently disabling this advisory
        # gate is safer than blocking commits on a tooling regression.
        return 0
    return check_path_claim_coverage_at_commit.main([])


def run() -> int:
    _emit_diverged_warning()
    rc = _run_file_line_check_or_block()
    if rc != 0:
        return rc
    rc = _run_field_note_render_or_block()
    if rc != 0:
        return rc
    rc = _run_harness_capability_render_or_block()
    if rc != 0:
        return rc
    rc = _run_agent_render_check_or_block()
    if rc != 0:
        return rc
    rc = _run_worktree_status_check_or_block()
    if rc != 0:
        return rc
    return _run_path_claim_coverage_check_or_block()


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
