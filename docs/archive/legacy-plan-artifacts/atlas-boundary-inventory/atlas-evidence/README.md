# Atlas Evidence — authoring inputs for the Atlas ticket set

Three working-draft files landed in-repo on 2026-05-20 as authoring evidence for the Atlas ticket set. Authoritative Atlas spec lives in `strategy/GEN-3-PLAN.md` §3 Phase 0 (G3.P0.I1, I4, I5, I6, I7, I8).

Sections in these files that were **subsumed by the Atlas master plan have been removed** with stub paragraphs noting the supersession; what remains is the authoring detail Atlas references but doesn't carry.

| File | What it carries | Atlas ticket that consumes it when filing |
|---|---|---|
| `yoke-recipe-spec.md` | 26 drafted recipes with VETTED-LIVE / VETTED-TELEMETRY / VETTED-SOURCE markers; Section 6b "Critical Findings from Live Vetting" (port 8765 gotcha, actor_id-as-string requirement, items.progress_log.append payload field names, etc.) | Atlas Ticket 3 (Tier 1 Universal Packet Recipes) |
| `yoke-telemetry-frequency-table.md` | 14-day raw telemetry (~127k Bash calls); per-invoker top-30 breakdown for main session + each subagent; NextActionChosen skill-attribution analysis; Section K Guardrail Review (G-01 through G-08); SessionCwdMismatchDenied bucket analysis | Atlas Tickets 1, 3, 4, 5 (T1 catalog; T3/T4/T5 telemetry baselines) |
| `yoke-recipe-top-down.md` | First-principles agent tree; per-role recipe inventory (main, engineer, tester, simulator, architect, boss, PM, PD); operation taxonomy; Section F "UNEXPECTED categories" (sed-doc reads, env-prefix invocations, inline Python) | Atlas Tickets 1, 3 (T1 family classification; T3 per-role authoring) |

## What was removed

- Recipe-ID schemes (`R-XX-NN`, `seq.*`) — Atlas dropped runtime recipe IDs entirely
- Anti-pattern doctrine blocks — Atlas dropped anti-pattern packet entries entirely (negative teaching is denial-message work only)
- Recipe priority maps that re-state Atlas's tier system
- Implementation plans and open-questions rosters that Atlas's master plan supersedes
- Cross-reference contracts that depended on the dropped recipe-ID system

## What was retained

- Raw telemetry tables and analysis
- The 26 drafted recipes (as authoring input for Atlas Ticket 3)
- Live-vetting findings (critical gotchas — port 8765, actor_id-as-string, etc.)
- Per-role and per-skill recipe inventories
- Guardrail review (G-01 through G-08 gap report)
- Cross-reference matrix between top-down inventory and bottom-up telemetry

## Workflow

When the operator (or operator-directed agent) files Atlas Ticket 3 (Tier 1 Universal Packet Recipes), they quote-paste evidence from `yoke-recipe-spec.md` and `yoke-telemetry-frequency-table.md` into the ticket body. Same pattern for T1 (catalog), T4 (help text), T5 (denials).

These files are NOT generated artifacts. They were produced by hand during the Atlas drafting session. The Atlas master plan's `atlas_*` runners (T1's deliverables) produce a different artifact bundle (`destination-map-and-teaching-YYYY-MM-DD/`) when they land.
