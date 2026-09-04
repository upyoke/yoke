"""HC asserting Yoke checkouts are not Codex hook-dead zones.

Codex persists hook trust against the literal path of the hooks file it
loaded, so a linked worktree — which materializes the checkout's tracked
``.codex/hooks.json`` symlink at its own absolute path — inherits none of the
checkout's trust. Untrusted hooks do not run, so a Codex thread working in an
unmirrored worktree registers no session and emits no telemetry, and the
silence is indistinguishable from a quiet session.

Project install mints trust for the main checkout, and worktree preparation
mirrors that trust (see
``yoke_core.domain.worktree_codex_hook_trust``). This check is the backstop
for an untrusted main checkout, lanes created before mirroring ran, persisted
hashes that no longer match Codex's normalized identity, and trust paths left
behind after checkout removal.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from yoke_core.domain.codex_hook_trust_store import (
    CodexHookTrustStoreError,
    SWEEP_COMMAND,
    hooks_file_for,
    inspect_hook_file_trust,
    retrust_recovery,
    stale_trust_scan,
)
from yoke_core.domain.worktree_codex_hook_trust import (
    codex_config_path,
    inspect_hook_trust,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
    _run,
)


_WORKTREES_DIR = ".worktrees"


def _main_checkout(repo_root: str) -> str:
    """Return Git's common checkout when Doctor starts in a linked lane."""
    result = _run(
        [
            "git",
            "-C",
            repo_root,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        timeout=30,
    )
    if result.returncode != 0 or not (result.stdout or "").strip():
        return repo_root
    common_dir = Path(result.stdout.strip())
    return str(common_dir.parent) if common_dir.name == ".git" else repo_root


def _linked_worktrees(repo_root: str) -> List[str]:
    """Return the managed lane paths git currently knows about."""
    result = _run(
        ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
        timeout=30,
    )
    if result.returncode != 0:
        return []
    managed_root = os.path.join(repo_root, _WORKTREES_DIR) + os.sep
    return [
        line[len("worktree ") :]
        for line in (result.stdout or "").splitlines()
        if line.startswith("worktree ")
        and line[len("worktree ") :].startswith(managed_root)
    ]


def hc_worktree_hook_trust(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Main checkout and linked worktrees carry exact Codex hook trust."""
    name = "HC-worktree-hook-trust"
    desc = "Main checkout and linked worktrees carry exact Codex hook trust"
    resolved_root = _resolve_repo_root()
    if not resolved_root:
        rec.record(name, desc, "FAIL", "could not resolve the repo root")
        return
    repo_root = _main_checkout(resolved_root)

    config = codex_config_path()
    main = inspect_hook_file_trust(hooks_file_for(repo_root), config_path=config)
    if not main.approved:
        rec.record(
            name,
            desc,
            "FAIL",
            "\n".join(
                [
                    "Codex hooks will not fire in the main checkout:",
                    f"  - {main.summary()}",
                    f"Recovery: {retrust_recovery(repo_root)}",
                ]
            ),
        )
        return

    worktrees = _linked_worktrees(str(repo_root))
    dead: List[str] = []
    partial: List[str] = []
    blocked: List[str] = []
    for worktree in worktrees:
        result = inspect_hook_trust(str(repo_root), worktree, config_path=config)
        label = Path(worktree).name
        if result.stale:
            partial.append(f"{label}: {result.summary()}")
            continue
        if result.blocked_reason:
            blocked.append(f"{label}: {result.blocked_reason}")
        elif result.dead_zone:
            dead.append(f"{label}: none of {len(result.source_trusted)} trusted")
        elif not result.hooks_fire:
            partial.append(f"{label}: {result.summary()}")

    if dead or partial:
        rec.record(
            name,
            desc,
            "FAIL",
            "\n".join(
                ["Codex hooks will not fire in these worktrees:"]
                + [f"  - {row}" for row in dead + partial]
                + [f"  - {row}" for row in blocked]
                + [
                    "Preparing the lane again mirrors the checkout's trust; "
                    "hook content that differs from the trusted original "
                    "needs its own trust decision in Codex.",
                ]
            ),
        )
        return
    try:
        stale = stale_trust_scan(config_path=config)
    except CodexHookTrustStoreError as exc:
        rec.record(
            name,
            desc,
            "WARN",
            f"Codex stale trust scan refused: {exc}. Recovery: repair "
            f"{config}, then run `{SWEEP_COMMAND}`.",
        )
        return
    stale_detail = ""
    if stale.hook_keys or stale.project_paths:
        stale_detail = "\n".join(
            [
                f"Codex trust contains {len(stale.hook_keys)} hook entries "
                f"across {len(stale.hook_paths)} deleted hooks paths and "
                f"{len(stale.project_paths)} deleted project entries.",
                f"Recovery: run `{SWEEP_COMMAND}`.",
            ]
        )
    if blocked or stale_detail:
        details = [f"  - {row}" for row in blocked]
        if stale_detail:
            details.append(stale_detail)
        rec.record(name, desc, "WARN", "\n".join(details))
        return
    if not worktrees:
        rec.record(
            name,
            desc,
            "PASS",
            "main checkout carries exact hook trust; no linked worktrees present",
        )
        return
    rec.record(
        name,
        desc,
        "PASS",
        f"{len(worktrees)} linked worktrees carry the checkout's hook trust",
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "worktree-hook-trust",
        "Main checkout and linked worktrees carry exact Codex hook trust",
        hc_worktree_hook_trust,
    ),
)
