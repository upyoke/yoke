---
name: help
description: Show the Yoke command reference and quick-start guide.
argument-hint: ""
---

# /yoke help

Answer only the asked scope; read that command's `--help` or skill first. General help: `yoke --help`. Docs: `.yoke/docs/index.md`, else `https://upyoke.com/docs`. Setup from an agent session: `yoke setup --agent`, relaying each question.

<!-- BEGIN GENERATED: skill-registry -->
| Skill | Kind | Autonomy | Purpose |
|---|---|---|---|
| `/yoke blitz {PREFIX-N}` | stage | autonomous execution | execute document-led work |
| `/yoke charge [--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]` | orchestrator | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N [--max-attempts N] [--no-chain]` | stage | autonomous execution | execute generated task lanes |
| `/yoke curate (no arguments)` | utility | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash "spec" \| {PREFIX-N}` | stage | autonomous execution | execute spec-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | follow skill decision gates | adopt existing work and reach the first item done |
| `/yoke polish {PREFIX-N}` | stage | autonomous execution | review and finish implementation |
| `/yoke refine {PREFIX-N}` | stage | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync [--fix]` | utility | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd {PREFIX-N}` | stage | autonomous execution | execute the pinned planning interval |
| `/yoke simulate {epic-ref} [--auto-fix] \| --system` | utility | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG] [--project P ...]` | orchestrator | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize [--model MODEL]` | orchestrator | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]` | stage | autonomous execution | merge and deliver an item |
| `/yoke wrapup (no arguments)` | utility | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->
