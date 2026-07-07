<!-- Last refreshed: 2026-04-11 (YOK-1373 Phase F — zero-shell deprecation banner). -->
# Shell Scripts Reference — **RETIRED**

> **Deprecated as of YOK-1371 (literal zero shell).** Every tracked `.sh` file listed below has been deleted. This document is retained only as a historical map from retired script names to the Python owner that replaced them. Do not treat any shell command below as a current operational instruction — use the Python entrypoints in the table at the top of this file.
>
> **Canonical Python entrypoints (use these instead):**
>
> | Retired shell surface | Python replacement |
> | --- | --- |
> | `yoke-db.sh <domain> ...` | `python3 -m runtime.api.cli.db_router <domain> ...` |
> | `project-db.sh ...` | `python3 -m runtime.api.cli.db_router projects ...` |
> | `schema-db.sh init` | `python3 -m runtime.api.cli.db_router init` |
> | `shepherd-db.sh ...` | `python3 -m runtime.api.cli.db_router shepherd ...` |
> | `ouroboros-db.sh ...` | `python3 -m runtime.api.cli.db_router ouroboros ...` |
> | `env-db.sh ...` | `python3 -m runtime.api.cli.db_router envs ...` |
> | `flow-db.sh ...` | `python3 -m runtime.api.cli.db_router flows ...` |
> | `release-notes-db.sh ...` | `python3 -m runtime.api.cli.db_router release ...` |
> | `rebuild-board.sh` | `python3 -m runtime.api.service_client backlog-cli rebuild-board` |
> | `render-body.sh <id>` | `python3 -m runtime.api.domain.render_body <id>` |
> | `service-client.sh <cmd>` | `python3 -m runtime.api.service_client <cmd>` |
> | `merge-worktree.sh ...` | `python3 -m runtime.api.engines.merge_worktree ...` |
> | `done-transition.sh <id>` | `python3 -m runtime.api.engines.done_transition <id>` |
> | `repair-status.sh ...` | `python3 -m runtime.api.engines.repair_status ...` |
> | `doctor.sh` | `python3 -m runtime.api.engines.doctor` (invoked by `/yoke doctor`) |
> | `discovery-scan.sh <id>` | `python3 -m runtime.api.domain.discovery_scan <id>` |
> | `update-status.sh <epic> <task> <status> [note]` | `python3 -m runtime.api.domain.update_status <epic> <task> <status> [note]` |
> | `check-hard-blocks.sh <id> [--gate-point <p>]` | `python3 -m runtime.api.domain.check_hard_blocks <id> [--gate-point <p>]` |
> | `check-ac-presence.sh <id>` | `python3 -m runtime.api.domain.check_ac_presence <id>` |
> | `persist-epic-simulation.sh <epic> <phase>` | `python3 -m runtime.api.domain.persist_simulation <epic> <phase>` |
> | `conduct-reviewed-handoff.sh <epic>` | `python3 -m runtime.api.domain.conduct_reviewed_handoff <epic>` |
> | `bootstrap-project.sh <project>` | `python3 -m runtime.api.domain.bootstrap_project cli <project>` |
> | `config-helper.sh get <key> [default]` | `python3 -m runtime.api.domain.runtime_settings get <key> [default]` |
> | `resolve-paths.sh <kind>` | `python3 -m runtime.api.domain.worktree paths <kind>` |
> | `create-worktree.sh ...` | `python3 -m runtime.api.domain.worktree create ...` |
> | `sync-to-github.sh <id>` | `python3 -m runtime.api.service_client backlog-cli sync-item <id>` |
> | `validate-test-commands.sh <project>\|--all` | `python3 -m runtime.api.domain.projects validate-test-commands <project>\|--all` (YOK-1378) |
> | Codex / session hook launchers | `python3 -m runtime.harness.session_hooks` and `python3 -m runtime.harness.codex.codex_hooks` |
> | `rebuild-board` orchestration | `runtime.api.domain.rebuild_board.rebuild(...)` (called in-process by `service_client backlog-cli rebuild-board`) |
> | Agent adapter generation | `python3 -m runtime.api.domain.agents_render` — renders canonical bodies from `runtime/agents/` into `runtime/harness/claude/agents/yoke-*.md` (which Claude reads through the `.claude/agents` symlink) |
>
> **Do not add tracked `.sh` files back.** See `AGENTS.md` → "Code Conventions" → "literal zero shell is the current contract". Ad hoc `sh -c user-supplied-command` remains permitted for shelling out to project test commands and similar user-provided hooks.
>
> **Skill-internal zero-shell contract (YOK-1438):** The zero-shell boundary extends beyond tracked entrypoints to Bash recipes inside `.agents/skills/yoke/**/*.md`. Shell glue that exists only to choreograph session IDs, temp-file content writes, or argument wrappers around Python CLIs is prohibited. Python CLIs resolve session state internally, and structured content flows through `--stdin` or the Write tool. See `docs/zero-shell-proof.md` → "Skill-Internal Contract" for the full prohibition and retained-boundary lists.
>
> The legacy content below this banner is preserved for historical context only — to help find what *used* to own a given operation. Skip it if you are trying to figure out what to run today.

---
