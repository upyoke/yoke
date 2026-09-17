# /yoke refine — critique doctrine

Read this before step 5's critique. The cardinal rule and the
escalate-don't-correct rule are on the entrypoint because they bind from
the first write; everything here shapes what the critique looks for.

## Corollaries (reinforcing the cardinal rule)

**Concrete decisions are sacred.** If the spec already contains concrete structural decisions — directory trees, file layouts, explicit "X stays at Y" / "X moves to Y" statements, specific naming choices, architectural diagrams, or interface shapes — those represent decisions the operator already approved. You may add discovery commands around them, add blast-radius analysis, or add supporting ACs — but you may NEVER abstract a concrete decision into vague prose. "The harness package unifies all harness code with Claude and Codex subdirectories" is a concrete decision. "A single truthful ownership model for harness code" is an abstraction that loses the decision.

**ACs are additive, not replacive.** You may add new ACs, renumber, improve wording, and add verification commands. You may NOT delete or replace the substance of an existing AC. Every concrete AC in the original must have a corresponding concrete AC in the enhanced version.

**User voice is verbatim.** When the spec contains content that is clearly the user's own words — numbered questions, direct observations, screenshots, "I saw X", "why does X", evidence references — that content must be preserved word-for-word. User questions define what the work item must answer; user evidence defines the ground truth the work item must address. Abstracting "what's the point of running CI in parallel with deployments?" into "document the tradeoff" loses the question the work item exists to answer.

## Operating principles

**Maximalist interpretation.** Read every work item as "make this fully work end-to-end so the operator can use and experience the result." A minimal interpretation that leaves obvious end-to-end requirements for a hypothetical future work item is a refinement failure. If a reasonable person would expect it to work, the work item should say so.

**Surface what's missing, not just what's unclear.** Refinement fills in what the operator obviously meant but didn't write. Missing error handling, missing cleanup of replaced state, missing documentation updates, missing blast-radius items. Do not fabricate unrelated scope or redesign the work item's purpose, but do complete the picture of what "done" actually looks like.

**Clean-slate mindset.** If the work item replaces, removes, or supersedes something, the spec must explicitly call out what gets deleted. The codebase after this work item should read as if the old way never existed.

**Simplest migration wins.** Default to hard cutover unless there is provably live data, live users, or live integrations that need graceful migration.

**Future-concept lens.** Generation labels are sequencing hints, not architecture walls. If a work item adds or changes `actor_id`, `session_id`, `heartbeat_at`, ownership, leases, claims, approvals, overrides, evidence, run records, execution journals, compiled packets, route-around facts, resource locks, or shared-state coordination, refine must decide whether this is the smallest honest v0 of a later end-state primitive. If yes, shape the spec around that primitive and the concrete current consumers. If no, require an explicit deletion or absorption target so a local workaround does not become accidental architecture.

**Dead weight has zero tolerance.** If the work item obsoletes code, tests, config keys, feature flags, utility functions, documentation sections, migration scripts, or re-exports, the spec must include their removal.

**Be the giant.** Your refined artifacts are the cold-start context for every downstream agent. Every gap you leave is a gap they'll hit. Do the investigative legwork: verify code references against the live codebase, include grep commands for blast-radius discovery, provide concrete examples.

**No such thing as "agent error."** When the critique reveals a bad artifact, the cause is systemic: insufficient dispatch context, ambiguous instructions, or upstream gaps. Frame every issue as what the SYSTEM should change to prevent it.

**Events table for investigation.** When critiquing artifacts, query the events table for diagnostic context: `yoke events query --item PREFIX-N`. Anomaly flags and envelope data reveal whether the artifact was produced under context pressure.

**File work items for root causes.** When refinement surfaces a systemic issue, note the root cause for work item filing.

**Think, don't just check.** The dimensions and rules in this skill are a starting point, not a ceiling. Step back and think about the work item as a whole: What is this work item actually trying to achieve? What would a thoughtful senior engineer expect "done" to look like? The checklist catches known failure modes; your judgment catches everything else.

