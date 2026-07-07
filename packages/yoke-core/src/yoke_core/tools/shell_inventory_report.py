"""Report rendering for the shell migration inventory.

Owns ``load_shell_files`` (the orchestrator that ties scanning + classification
into a sorted ``list[ShellFile]``) and ``render_markdown`` (the Markdown
emitter that writes ``docs/archive/shell-inventory.md``).
"""

from __future__ import annotations

import textwrap
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from yoke_core.tools.shell_inventory_classify import (
    ShellFile,
    candidate_home,
    classify,
    infer_owner,
    parse_functions,
)
from yoke_core.tools.shell_inventory_scan import (
    collect_text_files,
    count_callers,
    tracked_files,
)


def load_shell_files(root: Path) -> list[ShellFile]:
    files = tracked_files(root)
    shell_paths = [path for path in files if path.suffix.lower() == ".sh"]
    text_files = collect_text_files(root, files)
    caller_counts = count_callers(shell_paths, text_files)

    shell_files: list[ShellFile] = []
    for path in sorted(shell_paths):
        relpath = str(path.relative_to(root))
        try:
            line_count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            line_count = 0
        category, owner_hint, disposition, ticket, why_not_python = classify(path, relpath)
        owner = owner_hint if owner_hint != "Yoke runtime" else infer_owner(path)
        home = candidate_home(path)
        function_rows = parse_functions(path, home, disposition)
        if line_count < 150 and len(function_rows) < 3:
            function_rows = []
        shell_files.append(
            ShellFile(
                path=path,
                relpath=relpath,
                basename=path.name,
                line_count=line_count,
                caller_count=caller_counts.get(path.name, 0),
                category=category,
                owner=owner,
                disposition=disposition,
                ticket=ticket,
                why_not_python=why_not_python,
                candidate_home=home,
                function_rows=function_rows,
            )
        )
    return shell_files


def _execution_plan_lines() -> list[str]:
    return textwrap.dedent(
        """
        ## Current Execution Plan

        ### Where We Are Now (2026-04-11)

        - `zero-shell-bootstrap-closeout`, `zero-shell-cleanup-baseline`, and both grouped residual waves are merged.
          Wave 2 (`zero-shell-wave-two-start` through `zero-shell-wave-two-end`) plus `zero-shell-wave-two-integration` and
          `zero-shell-wave-two-proof` now live on `main`.
        - The repo has reached **semantic** zero-shell: no tracked `.sh` file is
          still classified as needing a fresh Python owner.
        - The remaining work is **literal shell extinction**. Every tracked
          `.sh` that survives today is either a compatibility contract, a
          runtime launcher, a shell test harness file, or a tracked external
          artifact template.
        - The per-file `Owner lane` column below is now the authoritative ownership
          map for the final closeout wave.

        ### How To Read The Remaining Buckets

        - `contingent shell coverage` means tests or harness helpers that only
          exist because shell entrypoints still exist.
        - `shell compatibility shim` means semantics already live in
          `runtime.api.*`, but a shell contract still survives for callers.
        - `runtime shell boundary` means the file is still acting as a launcher,
          hook, installer, or process wrapper. Wave 3 removes those boundaries
          too by replacing them with Python entrypoints or generated artifacts.
        - `migrate to Python` is no longer the gating metric. The real closeout
          metric is **zero tracked `.sh` files**.

        ### Literal Zero-Shell Objective

        - Success for this wave is `git ls-files '*.sh'` returning `0`.
        - A shell file whose semantics are already behind `yoke.api` is still
          residue until the shell contract itself disappears.
        - External project ops scripts may still be emitted at render/deploy
          time, but they should no longer be tracked as source files in this
          repo. Python or structured-data templates should own their truth.

        ### Zero-Shell Wave 3

        Wave 3 reuses the shared-branch pattern from the prior grouped waves,
        but the target is stricter: remove every tracked `.sh`, not just the
        semantic shell residue.

        ```
        main
         |-- db-wrapper-retirement worktree ----|
         |-- backlog-lifecycle-shell-retirement worktree ----|
         |-- hook-harness-shell-retirement worktree ----|
         |-- browser-deployment-qa-shell-retirement worktree ----|
         |-- worktree-merge-board-shell-retirement worktree ----+--> zero-shell-wave-3 --> zero-shell-shared-integration --> main --> zero-shell-final-proof
         |-- utility-installer-executor-shell-retirement worktree ----|         (shared branch)   integration    proof
         |-- external-artifact-shell-retirement worktree ----|
         `-- shell-test-runner-retirement worktree ----'
        ```

        Shared merge branch/worktree:

        - Branch: `zero-shell-wave-3`
        - Worktree: `/Users/dev/yoke/.worktrees/zero-shell-wave-3`
        - Every worker lane branches from that shared head, not from `main`.

        #### Worker Lanes

        - `db-wrapper-retirement` — remove the public DB shell CLI and DB-wrapper family.
          Owns every file whose `Owner lane` is `db-wrapper-retirement`: the `yoke-db.sh`
          router plus the remaining `*-db.sh` / `query-items.sh` wrapper set
          and their directly-mapped shell tests.
        - `backlog-lifecycle-shell-retirement` — remove the backlog/lifecycle shell contract. Owns
          `item-db.sh`, backlog registry / sync / done-transition style shells,
          lifecycle gate shims, and their directly-mapped shell tests.
        - `hook-harness-shell-retirement` — remove hook, harness, and event shell entrypoints. Owns
          hook/session/event shell surfaces plus `runtime/harness/**` and their
          directly-mapped shell tests.
        - `browser-deployment-qa-shell-retirement` — remove browser, deployment, and QA shell entrypoints.
          Owns Browser QA shells, deploy pipeline shells, and their
          directly-mapped shell tests.
        - `worktree-merge-board-shell-retirement` — remove worktree, merge, and board shell entrypoints.
          Owns worktree/merge utilities, board/render helpers, and their
          directly-mapped shell tests.
        - `utility-installer-executor-shell-retirement` — remove utility, installer, and executor shell
          entrypoints. Owns generic helper shims, runtime executors, install /
          start / restart launchers, and their directly-mapped shell tests.
        - `external-artifact-shell-retirement` — deshell tracked external artifacts. Owns template ops
          shell files, scaffold entrypoints, and the retired project artifact
          tree from the zero-shell cutover.
        - `shell-test-runner-retirement` — replace the shell test harness with an API-owned runner.
          Owns the generic shell test residue not mapped to another lane,
          plus the shell-test execution surfaces and project test-command
          registry path.
        - `zero-shell-shared-integration` — integration only. Owns shared caller/doc/config cutover,
          final launcher deletion, inventory refresh, and the grouped merge.
        - `zero-shell-final-proof` — final proof only. Owns the post-merge zero-shell proof
          ledger and the acceptance gate that the tracked shell count is
          literally zero.

        #### Shared Integration Surfaces

        Worker lanes must not edit these shared surfaces. They are integration-
        owned because they cut across multiple lanes:

        - `.agents/skills/yoke/**/SKILL.md`
        - `.claude/settings.json`, `.codex/hooks.json`, `.claude/rules/**`
        - `AGENTS.md` (and its `CLAUDE.md` compat symlink)
        - shared docs under `docs/**` that mention more than one lane:
          `db-reference.md`, `hook-parity-map.md`
        - global residue greps / final `git ls-files '*.sh'` enforcement

        #### File Ownership Contract

        - The per-file `Owner lane` column below is the exact ownership contract.
        - A worker lane owns the shell file, its Python replacement surfaces,
          and the shell tests mapped to that same owner lane below.
        - If a caller/doc/config surface references more than one worker lane,
          it is `zero-shell-shared-integration` integration-owned.
        - `shell-test-runner-retirement` owns every shell-test row whose owner lane is `shell-test-runner-retirement`; do
          not poach those generic workflow suites into the feature lanes.
        - No worker lane edits another lane's shell file even if the semantics
          are nearby.

        #### Safe Parallelism Rules

        - One issue = one worktree.
        - Branch every worker lane from `zero-shell-wave-3`, not `main`.
        - Merge every worker lane back into `zero-shell-wave-3` before running
          `zero-shell-shared-integration`.
        - Keep the shared branch green for the shell files and tests your lane
          deletes. Do not defer branch-green cleanup wholesale to integration.
        - Worker lanes do not touch the shared integration surfaces above.

        #### Existing Tickets To Reuse

        - `shell-test-runner-retirement` is no longer a side quest. It is Wave 3's shell-test
          harness / API-runner lane.
        - `zero-shell-final-proof` is no longer a generic proof reminder. It is the final
          zero-shell closeout gate after Wave 3 merges.

        #### How To Execute Wave 3

        1. Refresh or recreate `/Users/dev/yoke/.worktrees/zero-shell-wave-3`
           on branch `zero-shell-wave-3` from `main`.
        2. File / refine `db-wrapper-retirement` through `external-artifact-shell-retirement`, plus the updated
           `shell-test-runner-retirement`, against that shared branch/worktree.
        3. Dispatch `db-wrapper-retirement` through `external-artifact-shell-retirement` and `shell-test-runner-retirement` in parallel.
        4. Merge worker lanes back into `zero-shell-wave-3` as they clear
           verification.
        5. Run `zero-shell-shared-integration` once every worker lane has landed on the shared
           branch.
        6. Merge `zero-shell-wave-3` to `main`.
        7. Run `zero-shell-final-proof` and fail closeout unless the tracked shell count is
           literally zero.
        """
    ).strip("\n").splitlines()


def render_markdown(root: Path, shell_files: list[ShellFile]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    disposition_counts = Counter(file.disposition for file in shell_files)
    category_counts = Counter(file.category for file in shell_files)
    contingent_test_count = sum(1 for file in shell_files if file.category == "shell test")
    contingent_test_lines = sum(file.line_count for file in shell_files if file.category == "shell test")
    runtime_boundary_count = sum(1 for file in shell_files if file.category == "runtime shell boundary")
    migrate_queue_count = sum(1 for file in shell_files if file.disposition == "migrate to Python")
    migrate_queue_lines = sum(file.line_count for file in shell_files if file.disposition == "migrate to Python")

    lines: list[str] = []
    lines.append("# Shell Migration Inventory")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append(f"Repo root: `{root}`")
    lines.append("")
    lines.append("This inventory is the canonical shell-file ledger for the zero-shell-bootstrap-closeout closeout and the post-merge zero-shell wave that follows it.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total `.sh` files: **{len(shell_files)}**")
    lines.append("- Disposition counts:")
    for disposition, count in sorted(disposition_counts.items()):
        lines.append(f"  - `{disposition}`: {count}")
    lines.append("- Category counts:")
    for category, count in sorted(category_counts.items()):
        lines.append(f"  - `{category}`: {count}")
    lines.append(
        f"- Honest read: `{contingent_test_count}` shell tests / `{contingent_test_lines:,}` lines are contingent coverage, not the permanent shell floor."
    )
    lines.append(
        f"- Remaining literal-zero-shell gap: `{runtime_boundary_count}` runtime boundary scripts still need Python entrypoints, plus the tracked shell-test and external-artifact residue above."
    )
    lines.append(
        f"- Real Python migration queue: `{migrate_queue_count}` files / `{migrate_queue_lines:,}` shell lines."
    )
    lines.append("")
    lines.extend(_execution_plan_lines())
    lines.append("## File Inventory")
    lines.append("")
    lines.append("| Path | Lines | Callers | Category | Owner | Disposition | Owner lane | Why not Python yet? |")
    lines.append("|------|------:|--------:|----------|-------|-------------|--------|---------------------|")
    for file in shell_files:
        lines.append(
            f"| `{file.relpath}` | {file.line_count} | {file.caller_count} | {file.category} | "
            f"{file.owner} | {file.disposition} | {file.ticket} | {file.why_not_python} |"
        )

    function_files = [file for file in shell_files if file.function_rows]
    if function_files:
        lines.append("")
        lines.append("## Function Inventory")
        lines.append("")
        lines.append("Large or multi-responsibility shell files get function-level decomposition below.")
        for file in function_files:
            lines.append("")
            lines.append(f"### `{file.relpath}`")
            lines.append("")
            lines.append("| Function | Purpose | Candidate Python Home | Why still shell? |")
            lines.append("|----------|---------|-----------------------|------------------|")
            for function_name, purpose, home, rationale in file.function_rows:
                purpose_text = purpose.replace("|", "\\|")
                rationale_text = rationale.replace("|", "\\|")
                lines.append(
                    f"| `{function_name}` | {purpose_text} | `{home}` | {rationale_text} |"
                )

    return "\n".join(lines) + "\n"
