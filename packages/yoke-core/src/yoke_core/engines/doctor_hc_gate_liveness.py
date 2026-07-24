"""Doctor health check — the pre-commit file-line gate is actually live.

``yoke project install`` writes the file-line gate as a ``.git/hooks/pre-commit``
shim that ``exec``s ``yoke git pre-commit``. Two ambient conditions silently
shadow it: a ``core.hooksPath`` git setting that points git at a *different*
hooks directory, or a foreign / missing ``pre-commit`` in the effective hooks
directory. Either way the commit gate that is supposed to enforce the file-line
policy never runs, and nothing surfaces the fact.

This HC resolves the EFFECTIVE hooks directory the same way git does — honoring
``core.hooksPath`` when set, else ``<root>/.git/hooks`` — and inspects its
``pre-commit`` for the Yoke marker. PASS when the live shim is the Yoke gate;
WARN (never FAIL) when a foreign hooksPath shadows it or the effective hook is
foreign / missing. Self-skips silently when the repo root can't be resolved or
the checkout is not a git repo (no ``.git``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_contracts.git_hook_markers import PRE_COMMIT_MARKER

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

CHECK_ID = "gate-liveness"
CHECK_NAME = "Pre-commit gate is the live Yoke shim"


def _core_hooks_path(root: Path) -> Optional[str]:
    """Return the configured ``core.hooksPath`` for ``root``, or None."""
    r = _base._run(["git", "-C", str(root), "config", "--get", "core.hooksPath"])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return None


def hc_gate_liveness(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-gate-liveness: the effective pre-commit hook is the Yoke gate."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        return
    root = Path(repo_root)
    if not (root / ".git").exists():
        # Not a git repo (no .git) — nothing to verify. SKIP silently.
        return

    default_hooks_dir = root / ".git" / "hooks"
    core_hooks_path = _core_hooks_path(root)
    if core_hooks_path:
        candidate = Path(core_hooks_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        effective_hooks_dir = candidate
    else:
        effective_hooks_dir = default_hooks_dir

    pre_commit = effective_hooks_dir / "pre-commit"
    marker_present = False
    if pre_commit.is_file():
        try:
            content = pre_commit.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        marker_present = PRE_COMMIT_MARKER in content

    if marker_present:
        rec.record(
            CHECK_ID, CHECK_NAME, "PASS",
            f"The effective pre-commit hook ({pre_commit}) is the Yoke gate.",
        )
        return

    shadows_default = bool(core_hooks_path) and (
        effective_hooks_dir.resolve() != default_hooks_dir.resolve()
    )
    if shadows_default:
        detail = (
            "core.hooksPath shadows the Yoke pre-commit gate.\n"
            f"  git is configured to run hooks from {core_hooks_path}, not "
            f"{default_hooks_dir}, and that directory's pre-commit is not the "
            "Yoke shim — the file-line commit gate never runs.\n"
            "  Unset it (git config --unset core.hooksPath) or point it at "
            ".git/hooks, then reinstall with `yoke project install`."
        )
        rec.record(CHECK_ID, CHECK_NAME, "WARN", detail)
        return

    detail = (
        "The pre-commit file-line gate is not active.\n"
        f"  The effective pre-commit hook ({pre_commit}) is missing or is not "
        "the Yoke shim, so commits are not gated by the file-line policy.\n"
        "  Reinstall the managed git hooks with `yoke project install`."
    )
    rec.record(CHECK_ID, CHECK_NAME, "WARN", detail)


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "hc_gate_liveness",
]
