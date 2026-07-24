"""Authored-file line-limit checker.

The rule: no authored tracked text file may grow past the project limit. The
checker classifies every tracked file, reports per-file line counts, and
hard-fails in the changed-files check when:

    1. A new authored file lands over the limit.
    2. An existing authored file that is already over-limit grows further.
    3. An existing authored file crosses the limit upward (under to over).

Temporary-exception files are explicitly exempted from both warnings and
hard-fails. The product-safe checker in ``yoke_harness`` is the canonical
enforcement surface for installed projects; this source-dev checker mirrors
the same repo-local policy reader for manual scans.

Operator escape hatch: ``git commit --no-verify`` bypasses the pre-commit
invocation.

CLI:

    python3 -m yoke_core.domain.file_line_check report [--json]
    python3 -m yoke_core.domain.file_line_check check [--base REF | --staged] [--json]

Exit codes: ``0`` success / no hard-fail, ``1`` hard-fail or verdict
failure, ``2`` internal error (non-git tree, missing base ref, etc.).
"""

from __future__ import annotations

import fnmatch
import pathlib
import sys

from yoke_core.domain.file_line_check_helpers import (
    ChangedFile,
    CheckVerdict,
    Classification,
    FileEntry,
    build_parser,
    classify_change,
    collect_changed_paths,
    do_classify_path,
    git_show_line_count,
    head_exists,
    head_new_count,
    line_count_file,
    print_report,
    print_verdict,
    run_git,
    staged_new_count,
)
from yoke_contracts.project_contract.file_line_policy import (
    DEFAULT_LIMIT,
    default_exception_globs,
    resolve_file_line_policy,
    generated_path_globs,
    tracked_generated_views,
)
from yoke_core.domain.file_line_check_helpers import EMPTY_TREE as _EMPTY_TREE
from yoke_core.domain.strategy_docs_paths import is_strategy_view_path


LIMIT: int = DEFAULT_LIMIT

# Built-in exceptions live in yoke_contracts so this source-dev checker and
# the product-safe checker share one default set. Project-local additions live
# in .yoke/project.config and are resolved per repo_root at run time.
TEMPORARY_EXCEPTIONS: tuple[str, ...] = default_exception_globs()

# Explicit archive exceptions: historical docs are intentionally excluded
# from authored-file enforcement, but keep their archive classification.
ARCHIVE_EXCEPTIONS: tuple[str, ...] = (
    "docs/archive/**",
)


__all__ = (
    "LIMIT",
    "TEMPORARY_EXCEPTIONS",
    "ARCHIVE_EXCEPTIONS",
    "Classification",
    "FileEntry",
    "ChangedFile",
    "CheckVerdict",
    "resolved_policy",
    "classify_path",
    "inventory",
    "changed_files_check",
    "main",
)


def resolved_policy(repo_root: pathlib.Path):
    """Resolve the limit and exception globs from checked-in project policy.

    This is deliberately the same call the offline pre-commit checker
    makes, so the git hook and this source-dev checker can never disagree
    about the limit.
    """
    return resolve_file_line_policy(repo_root)


def classify_path(path: str, *, repo_root: pathlib.Path) -> Classification:
    """Classify ``path`` (repo-relative, POSIX) into a single category.

    Evaluation order is first-match-wins; the order mirrors the spec:
    symlink, TEMPORARY_EXCEPTIONS glob, archive, lockfile, generated,
    data asset, vendored, binary, authored default.
    """
    policy = resolved_policy(repo_root)
    return _classify_path_with_policy(path, repo_root=repo_root, policy=policy)


def _classify_path_with_policy(
    path: str, *, repo_root: pathlib.Path, policy
) -> Classification:
    posix_path = path.replace("\\", "/")
    if _is_rendered_strategy_doc(path, repo_root=repo_root):
        return Classification.GENERATED
    if posix_path in tracked_generated_views():
        return Classification.GENERATED
    # Tracked path shape, never the gitignored install manifest: a fresh
    # clone or CI runner has no manifest, and a verdict that changes with
    # the environment is not a gate.
    if any(fnmatch.fnmatchcase(posix_path, p) for p in generated_path_globs()):
        return Classification.GENERATED
    return do_classify_path(
        path,
        repo_root=repo_root,
        temporary_exceptions=policy.exception_globs,
        archive_exceptions=ARCHIVE_EXCEPTIONS,
    )


def _is_rendered_strategy_doc(path: str, *, repo_root: pathlib.Path) -> bool:
    """True for DB-rendered ``.yoke/strategy/*.md`` views."""
    if not is_strategy_view_path(path.replace("\\", "/")):
        return False
    abs_path = repo_root / path
    try:
        if abs_path.is_symlink():
            return False
        text = abs_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    from yoke_core.domain.strategy_docs_header import (
        StrategyHeaderError,
        parse_file_text,
    )

    try:
        parse_file_text(text)
    except StrategyHeaderError:
        return False
    return True


def inventory(*, repo_root: pathlib.Path) -> list[FileEntry]:
    """Return per-file classification + line count for every tracked file."""
    result = run_git(["ls-files"], repo_root=repo_root)
    if result.returncode != 0:
        return []
    policy = resolved_policy(repo_root)
    entries: list[FileEntry] = []
    for raw in result.stdout.splitlines():
        path = raw.strip()
        if not path:
            continue
        classification = _classify_path_with_policy(
            path, repo_root=repo_root, policy=policy
        )
        if classification in (Classification.SYMLINK, Classification.BINARY):
            entries.append(
                FileEntry(path=path, line_count=0, classification=classification)
            )
            continue
        abs_path = repo_root / path
        entries.append(
            FileEntry(
                path=path,
                line_count=line_count_file(abs_path),
                classification=classification,
            )
        )
    entries.sort(key=lambda e: e.path)
    return entries


def _build_changed_file(
    path: str,
    *,
    repo_root: pathlib.Path,
    base: str | None,
    staged: bool,
    policy,
) -> ChangedFile:
    classification = _classify_path_with_policy(
        path, repo_root=repo_root, policy=policy
    )
    if staged:
        old_ref = "HEAD" if head_exists(repo_root) else _EMPTY_TREE
        old = git_show_line_count(old_ref, path, repo_root=repo_root)
        new = staged_new_count(path, repo_root=repo_root)
    else:
        old = git_show_line_count(base or "main", path, repo_root=repo_root)
        new = head_new_count(path, repo_root=repo_root)
    return ChangedFile(
        path=path,
        classification=classification,
        old_line_count=old,
        new_line_count=new,
        delta=new - old,
    )


def changed_files_check(
    *,
    repo_root: pathlib.Path,
    base: str | None = None,
    staged: bool = False,
) -> CheckVerdict:
    """Diff-based hard-fail check. Fail-closed on non-git / missing base."""
    try:
        paths = collect_changed_paths(
            repo_root=repo_root, base=base, staged=staged
        )
    except (RuntimeError, FileNotFoundError):
        return CheckVerdict(
            ok=False,
            hard_fails=[],
            warnings=[],
            summary="not a git working tree or base ref unknown",
        )
    policy = resolved_policy(repo_root)
    hard_fails: list[ChangedFile] = []
    warnings: list[ChangedFile] = []
    for path in paths:
        change = _build_changed_file(
            path, repo_root=repo_root, base=base, staged=staged, policy=policy
        )
        is_hard, is_warn, _label = classify_change(
            old=change.old_line_count,
            new=change.new_line_count,
            limit=policy.limit,
            classification=change.classification,
        )
        if is_hard:
            hard_fails.append(change)
        elif is_warn:
            warnings.append(change)
    ok = not hard_fails
    if ok and not warnings:
        summary = (
            f"ok: no authored file violations across {len(paths)} changed paths"
        )
    elif ok:
        summary = f"ok with {len(warnings)} warning(s)"
    else:
        summary = f"{len(hard_fails)} hard-fail(s), {len(warnings)} warning(s)"
    return CheckVerdict(
        ok=ok, hard_fails=hard_fails, warnings=warnings, summary=summary
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(LIMIT)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    repo_root = (
        pathlib.Path(args.repo).resolve() if args.repo else pathlib.Path.cwd()
    )
    try:
        policy = resolved_policy(repo_root)
        if args.cmd == "report":
            entries = inventory(repo_root=repo_root)
            print_report(entries, limit=policy.limit, as_json=args.json)
            return 0
        if args.cmd == "check":
            effective_base = None if args.staged else (args.base or "main")
            verdict = changed_files_check(
                repo_root=repo_root,
                base=effective_base,
                staged=args.staged,
            )
            print_verdict(verdict, as_json=args.json)
            return 0 if verdict.ok else 1
    except Exception as exc:  # pragma: no cover — defensive CLI boundary.
        print(f"file_line_check: internal error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
