"""Fast-fail repo contracts for CI — tree-only checks before the pytest matrix.

Runs deterministic checkout contracts on one runner so a stale atlas,
install-bundle drift, authored-file overage, or ruff violation fails in
about a minute instead of spinning the eight-shard suite. Each named
contract prints PASS/FAIL; failures also land in ``$GITHUB_STEP_SUMMARY``
when that file is set. The shard suite keeps its own copies of these
assertions as defense in depth.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, List, Optional, Sequence, Tuple


ContractFn = Callable[[Path, Optional[str]], Tuple[bool, str]]


def _append_summary(lines: Sequence[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _changed_python_paths(repo_root: Path, base: str) -> List[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base}...HEAD",
            "--",
            "*.py",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git diff failed: {detail or 'unknown error'}")
    return [line for line in completed.stdout.splitlines() if line.endswith(".py")]


def check_authored_file_limit(
    repo_root: Path, base: Optional[str],
) -> Tuple[bool, str]:
    if not base:
        return True, "skipped (no --base; PR-only delta check)"
    from yoke_harness.git_hooks import file_line_check as flc

    verdict = flc.changed_files_check(repo_root=repo_root, base=base, staged=False)
    if verdict.ok:
        return True, verdict.summary
    return False, verdict.summary


def check_changed_path_ruff(
    repo_root: Path, base: Optional[str],
) -> Tuple[bool, str]:
    if not base:
        return True, "skipped (no --base; PR-only delta check)"
    paths = _changed_python_paths(repo_root, base)
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
    repo_root: Path, _base: Optional[str],
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
    repo_root: Path, _base: Optional[str],
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


def run_contracts(
    repo_root: Path, *, base: Optional[str] = None,
) -> int:
    """Execute every contract; return 0 only when all pass."""
    summary_lines = ["## Repo contracts", ""]
    failures: List[str] = []
    for name, fn in CONTRACTS:
        try:
            ok, detail = fn(repo_root, base)
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
        default=None,
        help="Git base ref for delta checks (authored-file + changed-path ruff).",
    )
    parser.add_argument("--repo", default=None, help="Checkout root (default: cwd).")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_contracts(_resolve_repo_root(args.repo), base=args.base)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTRACTS",
    "check_atlas_currency",
    "check_authored_file_limit",
    "check_changed_path_ruff",
    "check_install_bundle_tree",
    "main",
    "run_contracts",
]
