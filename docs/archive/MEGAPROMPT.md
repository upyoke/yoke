You are conducting a major periodic strategic checkpoint for the Yoke project.

Your job is to produce a high-signal “State of Yoke” analysis that maximizes alignment, momentum, and strategic correctness.

This is a read-only analysis pass.
Do not edit files.
Do not apply patches.
Do not run mutating commands.
Do not implement anything.
Analyze and synthesize only.

Your audience is the operator/boss.
Optimize for strategic usefulness, truthfulness, and prioritization.
Be decisive. Be evidence-based. Be explicit about uncertainty.
Use concrete dates whenever referring to “latest,” “current,” “today,” or recent changes.

Your output should feel like a strong internal strategic review, not a generic audit.

## Core Objective

Figure out, as accurately as possible:

1. What Yoke currently is.
2. What has changed since the last major checkpoint.
3. What Yoke is doing unusually well.
4. What is structurally wrong, stale, risky, wasteful, or misleading.
5. What the highest-leverage next moves are.
6. What outside patterns, products, code, or ideas Yoke should borrow from or ignore.
7. What the forward master plan should be at a high level.

## Hard Constraints

1. Read and analyze only. No edits.
2. Be selective. Do not brute-force everything if a smarter sampling strategy gets to the truth faster.
3. Prefer canonical sources and current operational evidence over older planning prose.
4. Distinguish clearly between:
   - observed fact
   - inference
   - recommendation
5. If external research is available, do it as a targeted delta scan, not an endless landscape dump.
6. Stay high-level. This is not an implementation sprint plan unless a deeper breakdown is absolutely necessary.
7. If some data is missing, say what is missing and how it limits confidence.

## Evidence Hierarchy

Work in this order.

### Phase 1: Ground in current internal reality

Read the canonical core first:
- `VISION.md`
- `PAD.md`
- `yoke/README.md`
- `yoke/BOARD.md`
- `yoke/docs/OVERVIEW.md`
- `yoke/.yoke/docs/db-reference.md`
- the current master plan document if one exists
- any especially central docs in `yoke/docs/` that appear to define the current architecture or operator surface

Then inspect current operational state:
- current board state and item distribution
- current DB table inventory and a few high-signal counts
- latest health report
- latest wrapups
- recent completed items
- any currently ready, active, blocked, frozen, or otherwise important items

### Phase 2: Review recent history without over-reading

Do not automatically read the full bodies of the last 100 items.

Instead:
1. Review metadata for the last 100 items.
2. Identify the 15-25 most strategically relevant items by a mix of:
   - recency
   - architectural impact
   - severity
   - repeated mention
   - cross-project significance
   - evidence of changing direction
3. Read those full bodies.
4. State which ones you selected and why.

### Phase 3: Analyze the database and events intelligently

Inspect the state of the codebase and the DB, but stay strategic.
You are looking for signal, not completeness theater.

Review:
- key table inventory
- count and distribution of items by status/project/type
- project / flow / run / QA / event footprint at a summary level
- event volume, event types, anomaly clusters, and anything interesting in recent telemetry
- any health-check warnings or recurring integrity noise
- any signs of schema drift, dead systems, stale abstractions, or observability blind spots

Do not read every event row unless a cluster justifies it.
Prefer summaries, distributions, anomalies, and targeted samples.

### Phase 4: Review documentation for drift and role-fit

Review the important docs and ask:
- which docs are canonical and accurate
- which docs are stale, misleading, redundant, or overgrown
- which important realities are under-documented
- where the docs describe a system that no longer exists

For the most important docs, simulate these readers:
- PM
- Architect
- Engineer
- Boss/operator

From each perspective, identify:
- what is clear
- what is missing
- what is wrong
- what would cause a bad decision or wasted time

Do not do this for every file in the repo.
Only do it for canonical docs and drift-suspect docs.

### Phase 5: External strategic scan

If internet access is available, do targeted external research into adjacent systems and patterns.
Prioritize overlap with Yoke’s actual direction.

Start with:
- StrongDM factory / software factory material
- gstack
- Cursor
- Claude Code
- Codex
- relevant agent-team / factory / spec-driven / eval / workflow systems
- any open-source repos or patterns you discover that appear directly adaptable

Do not turn this into a broad market report.
Focus on:
- patterns worth borrowing
- patterns to reject
- open-source code or architecture worth adapting
- strategic blind spots in Yoke’s current approach
- what others have solved better than Yoke
- what Yoke already does better than others

## What to Look For

Specifically look for:

- what Yoke is doing right
- what Yoke is doing wrong
- the top 5 flaws
- 3 game-changing business or product ideas grounded in reality
- what documentation is out of date
- where the codebase can be condensed, simplified, pruned, unified, or refactored
- duplicated systems
- stale abstractions
- operational waste
- maintenance-heavy surfaces that are no longer justified
- places where the architecture and the real behavior diverge
- evidence of drift between vision, docs, backlog, and implementation
- places where the system is impressive but fragile
- places where current momentum is going in the wrong direction
- places where current momentum is excellent and should be doubled down on

## Output Requirements

Produce a single strategic memo with these sections:

1. Executive Summary
2. Scale and Current State
3. What Changed Since the Last Checkpoint
4. What Yoke Is Doing Right
5. Top 5 Flaws
6. Critical Gaps and Risks
7. Documentation Drift and Knowledge Problems
8. Simplify / Prune / Refactor Opportunities
9. Competitive / Ecosystem Insights
10. 3 Game-Changing Ideas for Yoke
11. Top 10 Priorities in Recommended Sequence
12. High-Level Going-Forward Master Plan
13. What You Believe Now That You Would Not Have Said at the Start of This Review
14. Evidence, Assumptions, and Open Questions

## Style Requirements

- Be specific and opinionated.
- Use numbers where helpful.
- Use concrete examples.
- Name dates explicitly.
- Call out uncertainty when evidence is incomplete.
- Prefer synthesis over exhaustive inventory.
- Do not hide behind neutrality when the evidence points strongly in one direction.
- Do not go too deep into implementation detail.
- This is a strategic checkpoint, not a ticket-writing marathon.

## Final Standard

At the end, the operator should be able to answer:
- Where are we really?
- What changed?
- What matters most?
- What is broken or stale?
- What should we do next?
- What should we stop doing?
- What should we steal from the outside world?
- What is the high-level master plan from here?

If a tradeoff exists between completeness and usefulness, choose usefulness.

Save the final output memo to ./MASTER-PLAN.md.

---

MEGAPROMPT.md followup:
1. compare your doc to ./MASTER-PLAN-[FOE-NAME].md and tell me what you learn and what you would change in yours if you could
2. add this to the bottom of your doc in a separate section. title it REFLECTIONS AFTER READING MASTER-PLAN-[FOE-NAME].md
3. now read the section [FOE-NAME] added to his doc after reading yours

