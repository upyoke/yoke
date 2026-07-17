# Active — Implementation Guidance

Practical guidance for the implementation phase. Called by the active router as Phase 4 — the final phase before the agent begins coding.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`. This phase runs in the harness session that already acquired the work-claim and provisioned the worktree — same-session continuation, no manual relaunch. The session's authority over `{WORKTREE_PATH}` is its work-claim on YOK-{N}, validated per tool call by `lint_session_cwd` against `work_claims`.

---

## e-ctx. Use Project Context Summary

The project-context preflight now runs earlier in `implementing/project-context.md`, before the text-sensitive audit and before this file-discovery step.

Before you begin file discovery, re-read the `Project Context Summary` from that phase and use it directly:
- Start from the surfaced likely implementation files and known patterns.
- Reuse the surfaced likely test/doc surfaces when you need to cross-check helpers or fixtures.
- Treat broad Explore-style scans as a fallback for areas the project docs did not cover.

If the project-context phase self-skipped (Yoke item, no configured docs, or unreadable repo path), continue with the targeted discovery rules below.

## f. File Discovery Discipline

When locating files or code surfaces during implementation, prefer **targeted tools first**:

1. **Grep/Glob/Read for known targets.** If you know the filename, symbol, string, or pattern you need, use Grep, Glob, or Read directly. **For large known files where only a specific section is relevant** (e.g., a theme block near the end of a CSS file, a particular function in a long script), use the Read tool's `offset` and `limit` parameters to load only the needed range — this preserves context window budget and reduces noise.
2. **Exclude noise directories by default.** When using Glob or Grep, always exclude `node_modules`, `.git`, `dist`, `build`, `.next`, `__pycache__`, `.worktrees`, and similar generated/vendored directories.
3. **Reserve broad Explore-style scans for genuinely open-ended questions.**
4. **When using Explore, specify scope and depth.** Never dispatch an unconstrained "understand this area" prompt.

## f2. Stale Edit Handling

When performing multiple sequential edits to the same file, a later edit may fail with "String to replace not found" because an earlier edit already changed the target text. **This is a benign no-op, not a real failure.**

1. **Do not retry the exact same edit.** The target text no longer exists because a prior edit already achieved the intended change.
2. **Verify the desired state.** Re-read the file to confirm the intended change is already present. If it is, move on silently.
3. **Only escalate if the desired state is NOT present.**

## f3. Known-Pattern Recognition

Before launching a broad codebase exploration, check whether the current task matches a **known repeated pattern** — a category of change you have already seen in this project. Examples:

- **Theme page additions** (Buzz login pages): same route structure, same CSS pattern, same emoji animation scaffold. Do NOT re-explore the codebase for each new theme — reuse the pattern from the prior instance and adapt only the theme-specific values. The stale-string audit gate now structurally enforces test surface coverage — including helpers like `api-mocks.ts` and smoke files — before code changes begin. Trust the gate's pre-edit checklist rather than manual grep scoping.
- **Hook wiring additions** (Yoke PreToolUse/PostToolUse hooks): same `settings.json` schema, same matcher format, same script invocation pattern.
- **QA requirement seeding patterns**: same `yoke qa requirement add` call structure, differing only in `--success-policy`.

**Rule:** If you recognize the pattern from prior work in this session or from the item's context, skip broad exploration and go directly to implementation using the known structure. Only explore when you genuinely do not know the file layout or pattern.

## f4. Bulk Repetitive Replacement Strategy

When a change requires replacing the same pattern across many locations in a file (e.g., swapping a theme name in 20+ CSS class names, replacing a string in 50+ test assertions):

1. **Prefer `replace_all: true`** on the Edit tool when the old string is unique enough that a global replace is safe. This is a single tool call that replaces every occurrence.
2. **For patterns with slight variations**, use multiple targeted Edit calls — but group them logically (e.g., all class name renames in one pass, all text content changes in another) rather than one Edit per line.
3. **Never attempt a single giant `old_string` → `new_string` replacement** spanning 50+ lines of context. These are fragile — any whitespace or character mismatch causes the entire edit to fail. Instead, identify the minimal unique string that captures each replacement site.
4. **Verify after bulk edits.** After a `replace_all`, Grep the file for any remaining old-pattern instances to confirm completeness.

## f4b. Codebase-Reader Naming Before First Write

Assume future readers of the codebase will NOT have the ephemeral planning artifacts you are working from. Before creating or renaming any file, module, class, function, test, doc section, command, event, config key, constant, or comment, translate the item/plan/AC wording into current function, purpose, mechanics, or domain role.

Planning artifacts are scaffolding; the live codebase is the building. Do not copy ticket titles, strategy doc names, plan names, initiative labels, phase numbers, task numbers, AC/FR identifiers, branch names, worktree labels, or implementation-batch wording into live code or current-state docs unless the identifier is itself a runtime/domain concept. If a proposed name only makes sense to someone who can see the vanished plan, rename it before writing.

## f5. DB-Claim Stop-and-Amend

If, during implementation, you discover that the work touches a governed DB — schema changes against the project's authoritative DB, a new migration module, bulk data mutation, `migration_audit` writes — STOP coding and amend the DB claim before continuing. Do not silently push DB-mutating code under a stale `state="none"` claim.

1. Inspect the current claim: `yoke items get YOK-{N} db_mutation_profile`.
2. If it is `{"state":"none"}`, route the correction through the `db_claim.amend` function call:

   ```json
   {
     "function": "db_claim.amend",
     "actor": {"session_id": "<this-session>"},
     "target": {"kind": "item", "item_id": {N}},
     "intent": "implementation_db_mutation_discovered",
     "payload": {
       "reason": "implementation discovered governed DB mutation",
       "claim": { "<unified DB claim payload>": "..." }
     }
   }
   ```

3. The handler demultiplexes the claim payload into the `db_mutation_profile` and `db_compatibility_attestation` columns atomically; for `pre_merge_safe` claims the four authored attestation fields (`pre_merge_readers_writers`, `invariants`, `rehearsal_commands`, `residual_risk_notes`) are required inline. See [docs/db-reference.md](../../../../../docs/db-reference.md) for the full shape.
4. After the amendment lands, resume implementation. The advance to `reviewing-implementation` runs the prose-vs-claim gate (`GATE_DB_CLAIM_PROSE_MISMATCH`) and the evidence gate, both of which would block the transition with a stale negative claim.

Amending the YOK-{N} claim mid-implementation is supported and atomic — no lifecycle rollback to `idea` is required, and the amendment emits a `DbClaimAmended` event recording the previous claim, the new claim, your reason, and the validation result.

## g. Progress Checklist for Multi-Phase Missions

For non-trivial standalone items — those involving multiple phases such as implementation, test repair, QA recording, browser verification, and advance-to-implemented — consider creating a lightweight progress checklist to anchor your session.

**When to create:** Items that will span more than a few tool calls, involve multiple verification rounds, or include late-stage steps that are easy to forget after context compression.

**How to create:** If TodoWrite is available, use it to track phases. If not, emit a brief markdown checklist. Mark each phase complete as you finish it.

**When to skip:** Trivial single-file changes, documentation-only updates, or items where the full flow fits in a handful of tool calls.

## h. Parallel Execution of Independent Test Suites

When running local test suites after implementation, check whether suites are **truly independent** — each uses its own isolated temp directory, creates its own DB, and shares no mutable state. If so, run them in parallel (multiple Bash tool calls in one message).

**Safety conditions for parallel execution:**
- Each suite creates its own temp root (via `setup_test_repo` / `setup_full_script_db` / `mktemp -d`)
- No suite reads or writes another suite's temp directory
- No shared global state (env vars, singleton files, ports) that could cause races

**When NOT to parallelize:** Suites that share a DB, write to the same output file, depend on ordered execution, or use a shared network resource.

---

<!-- This re-anchoring block MUST remain the LAST section in the active-transition
 flow. Any future additions to QA seeding or post-active setup MUST go ABOVE this block,
 not below it. The agent loses the "begin implementation" thread after processing lengthy
 QA instructions — this block restates the directive so it is the final thing processed. -->

## Implementation Re-Anchor

**Do NOT end your turn. Begin implementation NOW.**

QA seeding is complete. Your next action MUST be a tool call. Here is what to do:

0. **`cd "{WORKTREE_PATH}"`** — make the worktree your shell's working directory before any further Read, Edit, Write, Grep, Glob, or test invocation. On sticky-cwd harnesses (Claude Code / Claude Desktop), this `cd` silently persists across subsequent Bash tool calls because `.worktrees/<branch>/` is inside the project root, so every later tool call automatically resolves relative paths against the worktree. On static-cwd harnesses (Codex's terminal), the `cd` does not persist between calls; continue to inline absolute paths under `{WORKTREE_PATH}` and use `git -C "{WORKTREE_PATH}" ...` for git ops. Either way, pytest invocations during the implementation / review loop — `python3 -m pytest`, `pytest`, `python3 -m yoke_core.tools.watch_pytest` — must collect and run from the worktree's tree, not the main checkout. The `watch_pytest` wrapper hard-refuses wrong-cwd invocations under a worktree-bearing claim with a one-line remediation message; the `cd` in this step is what keeps you out of that refusal.
1. **Read the acceptance criteria** from the item spec (structured field first, body fallback): `yoke items get {N} spec` — if empty, fall back to `yoke items get {N} body`.
2. **Read the File Budget** from the same spec/body. Implementation-bearing items must carry a `## File Budget` section seeded at idea time and hardened at refine. Obey it before writing the first new file: hard limit 350 lines per authored file (owned by `yoke_core.domain.file_line_check`), design target `<=300` lines so you keep editing headroom. If a planned file is missing from the budget, it is a refine miss — split the work to fit existing entries or stop and escalate rather than inventing a new oversized module. If you discover mid-implementation that the budget is fundamentally unrealistic (e.g., a file the budget gave one responsibility actually needs three), surface that immediately rather than landing oversized files. Late-stage enforcement (pre-commit, advance/polish gate, Tester verification, doctor) still uses `yoke_core.domain.file_line_check` as the canonical backstop — but it is a backstop, not the first line of defense.
3. **Note the Project Test Commands** surfaced in Phase 3 (test-and-record.md section a2). Use these — not ad-hoc discovery — when running tests.
4. **If the change touches user-visible copy, theme strings, labels, or UI text** — the stale-string audit preflight (Phase 3 section a3) MUST have already run. If it has not, trigger the source-dev/admin stale-string preflight helper for `YOK-{N}` and `{WORKTREE_PATH}` NOW before writing code. No registered product CLI wrapper exists yet; normal advance preflight/finalize owns this check. Finalize step 9 re-runs the blocking `verify` helper automatically before advance commits to `reviewing-implementation` / `reviewed-implementation`.
5. **Apply the simplify three-axis vocabulary at code-author time.** Use `AGENTS.md`'s `## Simplify — three-axis doctrine`: reuse existing surfaces first, keep the diff to the smallest AC-satisfying shape, justify new infrastructure against what already exists, and apply the future-concept lens when the change touches actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, run records, journals, packets, locks, or shared-state coordination.
6. **Apply codebase-reader naming before every first write.** Treat the ticket/plan/AC text as source context, not implementation vocabulary. New or renamed files, modules, helpers, tests, docs, commands, events, config keys, symbols, headings, and comments must describe current function/purpose/mechanics to a repository reader who cannot see the planning artifact.
7. **Begin implementing** the changes described in the spec, working entirely within the worktree at `{WORKTREE_PATH}`.
8. **Item context:** YOK-{N} — {title}.
9. **Long-running session continuity.** If your work spans multiple turns or might be picked up by a successor agent after compaction, write checkpoint notes to the **Progress Log** section on the item — see `AGENTS.md > Progress Log — long-running execution context on items` for the canonical incantation. Do NOT write session-continuity notes to `shepherd_log` (epic-only) or to the spec/technical_plan fields (intent, not state).

This is not optional — continuous flow from advance to implementation prevents wasted turns. Emit no end-of-turn summary. Your very next action must be a Read or Bash tool call.

## End-of-Implementation Chain Directive

`/yoke advance implementation` is a contract to reach `reviewed-implementation`, not to stop at "code passes tests." Record each ac_verification pass as you verify that AC (the gate will hard-block at advance time otherwise), then chain `/yoke advance YOK-{N} reviewing-implementation` → review loop → `/yoke advance YOK-{N} reviewed-implementation` back-to-back in the same turn. Go through `/yoke advance` for both transitions — raw `items update ... status` writes skip the finalize re-anchor and the claim lifecycle. Stop only for a real blocker, and when you do, name it.
