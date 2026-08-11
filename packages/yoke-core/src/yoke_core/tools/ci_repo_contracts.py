"""Fast-fail repo contracts for CI — tree-only checks before the pytest matrix.

Runs deterministic checkout contracts on one runner so a stale atlas,
install-bundle drift, authored-file overage, or ruff violation fails in
about a minute instead of spinning the eight-shard suite. Each named
contract prints PASS/FAIL; failures also land in ``$GITHUB_STEP_SUMMARY``
when that file is set. The shard suite keeps its own copies of these
assertions as defense in depth.

Every delta contract reads one changed-path scope, resolved once from the
merge-base of HEAD and the integration ref and deliberately independent of
which event started the run. A dispatched run checks out the branch tip and
a pull-request run checks out the merge commit; both share the same fork
point, so both must reach one verdict on one tree. Resolving the scope per
event is what lets a recorded-green gate stop predicting merge-queue entry.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ChangedPathScope:
    """The one diff every delta contract reads."""

    base_sha: str
    paths: Tuple[str, ...]

    @property
    def python_paths(self) -> List[str]:
        return [path for path in self.paths if path.endswith(".py")]


ContractFn = Callable[[Path, ChangedPathScope], Tuple[bool, str]]


def _append_summary(lines: Sequence[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail or 'unknown error'}")
    return completed.stdout


def resolve_changed_path_scope(
    repo_root: Path, integration_ref: str,
) -> ChangedPathScope:
    """Diff HEAD against its merge-base with *integration_ref*."""
    base_sha = _git(repo_root, "merge-base", "HEAD", integration_ref).strip()
    diff = _git(
        repo_root, "diff", "--name-only", "--diff-filter=ACMR", base_sha, "HEAD",
    )
    return ChangedPathScope(
        base_sha=base_sha,
        paths=tuple(line for line in diff.splitlines() if line),
    )


def check_authored_file_limit(
    repo_root: Path, scope: ChangedPathScope,
) -> Tuple[bool, str]:
    from yoke_harness.git_hooks import file_line_check as flc

    verdict = flc.changed_files_check(
        repo_root=repo_root, base=scope.base_sha, staged=False,
    )
    return verdict.ok, verdict.summary


def check_changed_path_ruff(
    repo_root: Path, scope: ChangedPathScope,
) -> Tuple[bool, str]:
    paths = scope.python_paths
    if not paths:
        return True, "no changed Python paths"
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *paths],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return True, f"ruff clean on {len(paths)} path(s)"
    detail = (completed.stdout or completed.stderr or "ruff failed").strip()
    return False, detail.splitlines()[0] if detail else "ruff failed"


def check_atlas_currency(
    repo_root: Path, _scope: ChangedPathScope,
) -> Tuple[bool, str]:
    from yoke_core.tools.atlas_integrity_audit import build_report
    from yoke_core.tools.atlas_render_docs import is_stale, render

    report = build_report(repo_root)
    body = render(report)
    if is_stale(repo_root, body=body):
        return False, (
            "docs/atlas.md is stale relative to the live audit report — "
            "run `python3 -m yoke_core.tools.atlas_render_docs render`"
        )
    return True, "docs/atlas.md matches the live audit render"


def check_install_bundle_tree(
    repo_root: Path, _scope: ChangedPathScope,
) -> Tuple[bool, str]:
    from yoke_core.domain import install_bundle_tree_sync

    drift = install_bundle_tree_sync.detect_drift(target_root=repo_root)
    if not drift:
        return True, "packaged install-bundle tree matches source"
    preview = "; ".join(drift[:3])
    more = f" (+{len(drift) - 3} more)" if len(drift) > 3 else ""
    return False, f"install-bundle tree drift: {preview}{more}"


CONTRACTS: Tuple[Tuple[str, ContractFn], ...] = (
    ("authored-file-limit", check_authored_file_limit),
    ("changed-path-ruff", check_changed_path_ruff),
    ("atlas-currency", check_atlas_currency),
    ("install-bundle-tree", check_install_bundle_tree),
)


def run_contracts(repo_root: Path, *, base: str) -> int:
    """Execute every contract against one scope; return 0 only when all pass."""
    summary_lines = ["## Repo contracts", ""]
    try:
        scope = resolve_changed_path_scope(repo_root, base)
    except (OSError, RuntimeError) as exc:
        # An unresolvable scope is a failure, never a silent skip: a contract
        # that reports PASS because it saw no files is indistinguishable from
        # one that ran, and that is the divergence this front exists to close.
        detail = f"changed-path scope against {base} unresolvable: {exc}"
        summary_lines.append(f"**Failed contracts:** {detail}")
        print(f"repo-contracts FAILED: {detail}", file=sys.stderr, flush=True)
        _append_summary(summary_lines)
        return 1
    failures: List[str] = []
    for name, fn in CONTRACTS:
        try:
            ok, detail = fn(repo_root, scope)
        except Exception as exc:  # noqa: BLE001 - surface any contract crash
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        status = "PASS" if ok else "FAIL"
        line = f"- **{name}**: {status} — {detail}"
        print(f"repo-contract {name}: {status} — {detail}", flush=True)
        summary_lines.append(line)
        if not ok:
            failures.append(name)
    summary_lines.append("")
    if failures:
        summary_lines.append(
            f"**Failed contracts:** {', '.join(failures)}"
        )
        print(
            f"repo-contracts FAILED: {', '.join(failures)}",
            file=sys.stderr,
            flush=True,
        )
    else:
        summary_lines.append("All repo contracts passed.")
        print("repo-contracts PASSED", flush=True)
    _append_summary(summary_lines)
    return 1 if failures else 0


def _resolve_repo_root(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if (parent / "runtime" / "api" / "tools").is_dir():
            return parent
    return cwd


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m yoke_core.tools.ci_repo_contracts",
        description=(
            "Run tree-only repo contracts that should fail CI before the "
            "pytest shard matrix starts."
        ),
    )
    parser.add_argument(
        "--base",
        required=True,
        help=(
            "Integration ref (e.g. origin/main). Every delta contract reads "
            "one diff taken from its merge-base with HEAD."
        ),
    )
    parser.add_argument("--repo", default=None, help="Checkout root (default: cwd).")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_contracts(_resolve_repo_root(args.repo), base=args.base)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTRACTS",
    "ChangedPathScope",
    "check_atlas_currency",
    "check_authored_file_limit",
    "check_changed_path_ruff",
    "check_install_bundle_tree",
    "main",
    "resolve_changed_path_scope",
    "run_contracts",
]
