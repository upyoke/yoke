# Agent Behavior Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-25: Tester reliability is the biggest conductor time sink

**First observed:** 2026-02-28 (YOK-195 T1 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 7+ entries across conductor sessions
**Status:** Partially addressed (YOK-204 pre-creates reviews dir, YOK-205 Tester output contract)

Across 8 tasks in YOK-195, at least 5 Tester dispatches failed to produce review files. Root causes: (1) reviews directory didn't exist in worktree — Tester can't mkdir, (2) Tester sometimes doesn't write the file even when instructed. YOK-201 (model escalation) and YOK-203 (explicit dispatch instructions) partially addressed this.

**Action:** YOK-204 done (dispatch pre-creates reviews/). YOK-205 covers Tester output contract. Remaining: auto-retry with escalated model after 2 failures.

---

## P-26: Documentation-as-enforcement fails under context pressure

**First observed:** 2026-02-24 (safe-worktree-lifecycle PM)
**Promoted:** 2026-03-01
**Occurrences:** 5+ documented failures (YOK-25, YOK-41, YOK-78, YOK-63, YOK-91)
**Status:** Active — ongoing design principle

Every "you MUST" in a SKILL.md is a potential failure point because LLMs under context pressure skip or reorder steps. The pattern of "document the constraint and trust the model to follow it" has failed at least 5 times.

**Action:** Code-level enforcement preferred (FR-3.5 sentinel + parse for YOK-91). Broader audit: identify SKILL.md "you MUST" instructions and replace with script-level enforcement where possible.

---

## P-27: Agent stall pattern at phase boundaries

**First observed:** 2026-03-01 (T1 conductor, YOK-213)
**Promoted:** 2026-03-01
**Occurrences:** 3+ documented instances (YOK-213 T1, YOK-454 T16, YOK-527)
**Status:** Mitigated — YOK-529

Multi-minute hang during transitions (test -> simulate, simulate -> merge) at ~69% context usage. Agent responds defensively when interrupted: "Not stuck — I was about to commit." This is confabulation — the agent was visibly stalled. Root cause: the LLM treats the end of processing a large Agent tool result as a natural conversation turn boundary and stops generating.

**Action:** YOK-529 added five mitigation layers to the conductor flow files:
1. **Autonomous Execution Mode declaration** — top-level section in `conduct/SKILL.md` setting the execution contract before any flow begins
2. **Continuation markers** — bold `AUTONOMOUS CONTINUATION REQUIRED` instructions at every subagent return boundary in `dispatch-context.md`, `batch-flow.md`, and `single-item.md`
3. **Post-subagent `[CONTINUE]` echo** — one-line status checkpoint forcing the model to produce text (preventing silent stop) while anchoring to the next step
4. **Output discipline instructions** — concise output directives in Engineer/Tester prompt templates to reduce large-result stop signals
5. **TodoWrite as continuation anchor** — checklist of batch milestones creating accountability pressure to continue

These are instruction-level mitigations (probabilistic, not deterministic). The stall pattern may still occur under extreme context pressure but at significantly reduced frequency.

---

## P-28: Worktree limits block parallel track execution

**First observed:** 2026-03-01 (T1, T5 conductors)
**Promoted:** 2026-03-01
**Occurrences:** 2+ entries
**Status:** Active — default limit may be too low for multi-track sprints

max_active_worktrees config exists but yoke/config is gitignored, so it can't be shared across sessions. YOK-254 had to work on main due to worktree limit.

**Action:** Recommendation: auto-scale limit based on active track count, or conductor should merge completed items before advancing later ones to reclaim worktree slots.
