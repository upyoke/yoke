---
name: do
description: "Autonomous session orchestrator — offers the session to Yoke's decision engine and routes to the chosen mode."
---

# /yoke do

Autonomous session orchestrator. Offers the current session to Yoke's decision engine, which inspects the frontier (runnable items, blocked items, SML state) and returns a `NextAction` directive. The directive is then routed to the appropriate mode handler.

After a chainable mode completes, the loop re-offers automatically up to `max_chain_steps` times.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events at every decision.** The decision engine emits `HarnessSessionOffered` and `NextActionChosen` events for a full audit trail. When investigating unexpected routing, query `yoke events query --event-name NextActionChosen --since "1 hour ago"` for the session's decision history.

**Identity is server-resolved, and the loop passes none of it.** Registration resolves a session's identity once — canonical executor, display alias, provider, model (including any `[variant]` suffix such as `[1m]`), execution lane, workspace, project, actor — and writes it to the session row. `yoke sessions identity` reads it back; `yoke sessions offer` reads the same row server-side. The loop never substitutes an identity value into a command line, because a locally guessed value would *override* correct server state rather than merely duplicate it: a session that passed its own guessed lane had every frontier item filtered behind a lane name its project declares no paths for, while an otherwise identical session that happened to pass nothing was routed correctly. The offer surface still accepts `--lane`, but only as a deliberate operator re-route — never as something this loop resolves. Two sessions with the same stored row must reach the same offer, so the loop passes only the step.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Read your session identity | `/yoke do` was just invoked | this file |
| 2. Call the decision engine | Identity is read back | [`loop.md`](loop.md) |
| — Audit a routing decision, or check a loop rule | An offer looks wrong, or you need the chaining/ownership contract | [`events-and-notes.md`](events-and-notes.md) |

## Steps

### 1. Read your session identity

Run `yoke sessions identity` as a single foreground call. It resolves the
calling session ambiently — no environment prefix, no `--session-id` — and
returns the stored identity: session id, canonical executor and its display
alias, provider, model, execution lane and the downstream paths that lane may
execute, workspace, project, actor, and `max_chain_steps`.

Every field comes from the authority, so none of it is advisory. Do not
resolve, detect, or mint any of it yourself, and do not pass any of it back
to a later call. If the read is refused because the session has no row, the
refusal names the recovery — hooks register sessions at start, so a missing
row is a hook-installation fact, not a cue to substitute a detected value.

### 2. Call the decision engine

Read the loop logic from `.agents/skills/yoke/do/loop.md` and follow those instructions.

The loop handles:
- Calling `yoke sessions offer --step N`
- Parsing the `NextAction` JSON response
- Routing to the correct mode handler
- Bounded chaining for chainable actions
