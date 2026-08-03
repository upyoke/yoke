"""HC asserting linked worktrees are not Codex hook-dead zones.

Codex persists hook trust against the literal path of the hooks file it
loaded, so a linked worktree — which materializes the checkout's tracked
``.codex/hooks.json`` symlink at its own absolute path — inherits none of the
checkout's trust. Untrusted hooks do not run, so a Codex thread working in an
unmirrored worktree registers no session and emits no telemetry, and the
silence is indistinguishable from a quiet session.

Worktree preparation mirrors that trust (see
``yoke_core.domain.worktree_codex_hook_trust``). This check is the backstop
for lanes created before the mirroring step ran, or whose entries were lost.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

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


def _linked_worktrees(repo_root: str) -> List[str]:
    """Return the managed lane paths git currently knows about."""
    result = _run(
        ["git", "-C", repo_root, "worktree", "list", "--porcelain"], timeout=30,
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
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Linked worktrees carry the checkout's Codex hook trust."""
    name = "HC-worktree-hook-trust"
    desc = "Linked worktrees carry the checkout's Codex hook trust"
    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(name, desc, "FAIL", "could not resolve the repo root")
        return

    config = codex_config_path()
    if not config.exists():
        rec.record(
            name, desc, "PASS",
            f"no Codex config at {config} — no hook trust to mirror",
        )
        return

    worktrees = _linked_worktrees(str(repo_root))
    if not worktrees:
        rec.record(name, desc, "PASS", "no linked worktrees present")
        return

    dead: List[str] = []
    partial: List[str] = []
    blocked: List[str] = []
    for worktree in worktrees:
        result = inspect_hook_trust(str(repo_root), worktree, config_path=config)
        label = Path(worktree).name
        if not result.source_trusted:
            # A checkout-wide condition, identical for every lane: there is
            # no trust to mirror, so there is no checkout-vs-lane delta to
            # report — Codex may simply be unused against this checkout.
            rec.record(
                name, desc, "PASS",
                result.blocked_reason or "no trusted Codex hook entries to mirror",
            )
            return
        if result.blocked_reason:
            blocked.append(f"{label}: {result.blocked_reason}")
        elif result.dead_zone:
            dead.append(f"{label}: none of {len(result.source_trusted)} trusted")
        elif not result.hooks_fire:
            partial.append(f"{label}: {result.summary()}")

    if dead or partial:
        rec.record(
            name, desc, "FAIL",
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
    if blocked:
        rec.record(name, desc, "WARN", "\n".join(f"  - {row}" for row in blocked))
        return
    rec.record(
        name, desc, "PASS",
        f"{len(worktrees)} linked worktrees carry the checkout's hook trust",
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        'worktree-hook-trust',
        "Linked worktrees carry the checkout's Codex hook trust",
        hc_worktree_hook_trust,
    ),
)
