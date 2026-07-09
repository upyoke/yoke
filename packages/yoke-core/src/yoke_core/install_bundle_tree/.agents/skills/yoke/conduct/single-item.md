# Single-Item Mode

Invoked by the conduct router when `YOK-N` is provided. This file is a **thin index** — execution is delegated to bounded phase files. **Inherited from router:** `SCRIPT_DIR`, `MAX_TESTER_REPROMPTS`, all parsed arguments. **Cross-references:** `dispatch-context.md` (steps 5m, 5n, 5p), `error-handling.md` (halt conditions).

When invoked with `YOK-N`, conduct operates on a single backlog item.

> **Conduct Shell Reminder:** Every Bash tool call is a **fresh shell**. Variables
> like `$SCRIPT_DIR` set in one Bash call do NOT exist in the next. In long sessions with many
> subagent dispatches, it is easy to forget this and paste literal `$SCRIPT_DIR` into a Bash
> call — which resolves to empty string, producing `/python3 -m yoke_core.cli.db_router`. Critical verdict-processing
> commands below use inline `SCRIPT_DIR="$(git rev-parse --show-toplevel)/.agents/skills/yoke/scripts"`
> as a safety net. When writing any new Bash call, always define SCRIPT_DIR inline or use the
> absolute path from MAIN_ROOT.

## Phase Files

Follow this phased-read sequence. **Read each file only when you reach that phase.**

| Phase | File | Description |
|---|---|---|
| 1 | `entry-activation.md` | S1–S6f: argument parsing, environment, gates, epic sync, task resolve, activation |
| 2 | `engineer-tester-loop.md` | S6g: Engineer/Tester dispatch loop, verdict processing, auto-chaining |
| 3 | `simulation-gate.md` | S6h: integration simulation, retry tiers, persist/verify, CLEAN/GAPS branching |
| 4 | `cleanup-report.md` | 6z/6z-cleanup/7: board rebuild, main-repo cleanup, final report, claim release |

**Start by reading `entry-activation.md`.** Each phase file ends with an explicit handoff to the next phase.

## Supplemental Files (read only when referenced)

- `dispatch-context.md` — Per-item context preparation, Engineer/Tester prompt templates, shared steps (reflection capture, artifact commit, post-pass advancement, epic auto-chaining). **Read only the section referenced by the current step** — use `offset`/`limit` on the Read tool.
- `simulation-autofix.md` — Automatic simulation gap resolution flow (Architect fix loop + amend cycle). Read only when `simulation-gate.md` Branch 3 triggers it.
- `error-handling.md` — Halt conditions, subagent dispatch summary, and implementation notes. Read for reference on halt behavior.
