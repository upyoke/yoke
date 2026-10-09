# Shepherd — resume and walk declared edges

First edge produces PM/design/Architect/Simulator artifacts. Later edges review
persisted artifacts; rerun Architect only for requested revision. Final edge
adds handoff gates. One-edge performs production and final gates before Boss.

Read persisted verdicts with worker/edge keys, fresh status and Progress Log.
READY/CAVEATS **Boss** completes review; Designer SKIPPED completes only Designer.
BLOCKED stops with evidence/recovery; NOT_READY resumes next attempt within
MAX_ATTEMPTS. Accepted review still owes lifecycle transition. Early planning
target status alone proves no review. If stage passed an unreviewed edge:
shepherd_verdict_missing names edge/artifacts; recover review, never skip it.

For each unfinished declared edge:
1. Reset current Scholar context; collect prior caveats.
2. First: [design-and-plan.md](design-and-plan.md); later: review existing artifacts.
3. Final (also single-edge): [planning-gates.md](planning-gates.md).
4. [boss-verdict.md](boss-verdict.md): persist/triage/transition.
5. [finalize.md](finalize.md): re-anchor and continue only inside binding.

Keep source/target/derived verdict key per edge. Completion requires fresh
status exactly through-stage; refreshed workflow supplies next bound skill.
