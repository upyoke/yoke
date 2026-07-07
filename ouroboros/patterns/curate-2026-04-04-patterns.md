# Patterns from 2026-04-04 Curate (1685 entries)

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-53: Specs with phantom code references waste engineering time

**First observed:** 2026-03-06 (across problem + friction entries)
**Promoted:** 2026-04-04
**Occurrences:** ~280 entries across engineer, PM, architect, tester, boss
**Status:** Partially addressed — codified in refine/polish, PM template, and Boss review; no automatic code-reference verifier yet

Specs that reference function names, column names, line numbers, or file paths from memory rather than verifying against the live codebase are the single largest source of wasted engineering time. Engineers investigate phantom references, discover they don't match reality, and must re-derive the correct approach.

**Action:** Refine now verifies referenced code against the live codebase before rewriting artifacts. Polish now verifies spec claims before trusting them. PM and Boss prompts both call out phantom references explicitly. Specs should use semantic anchors alongside any approximate line references.

---

## P-54: Blast radius needs grep discovery, not hardcoded file lists

**First observed:** 2026-03-06 (across all 4 categories)
**Promoted:** 2026-04-04
**Occurrences:** ~80 entries across engineer, tester, simulator, architect
**Status:** Partially addressed — refine/polish and spec validation now require discovery guidance on rename/removal-heavy work

Hardcoded file lists in specs are inherently incomplete. The pattern: spec lists 3 copies of a function, but there are actually 5. Engineer updates the listed ones, misses the unlisted ones. Half-migration.

**Action:** Refine now requires grep-based discovery commands in specs instead of file lists. `prd-validate.sh` blocks rename/removal-heavy specs that omit discovery guidance. Polish now treats residue grep as a required finishing check.

---

## P-55: Engineers complete core implementation but skip peripheral ACs

**First observed:** 2026-03-06 (across cross-critique + problem entries)
**Promoted:** 2026-04-04
**Occurrences:** ~80 entries across tester, engineer, boss
**Status:** Partially addressed — polish now treats peripheral ACs and test co-modification as mandatory review work

Engineers commonly finish the main code change but skip: test file updates, doc updates, dead code cleanup, help text updates, agent file updates, and commit discipline. The pattern: 40-60% of ACs addressed, all involving the core implementation. The remaining ACs (cleanup, docs, tests) are left undone.

**Action:** Polish now explicitly checks ALL ACs (not just core), requires test-{module}.sh co-modification audits, and treats residue grep as mandatory. Remaining enforcement still depends on the reviewer executing the checklist faithfully.

---

## P-56: Self-consistency drift within specs and plans

**First observed:** 2026-03-06 (across cross-critique + friction entries)
**Promoted:** 2026-04-04
**Occurrences:** ~60 entries across boss, PM, simulator
**Status:** Partially addressed — refine and Boss now require self-consistency checks, but there is no general contradiction linter

Specs written iteratively develop internal contradictions: FRs contradict non-goals, narrative sections written early don't reflect later requirement refinements, resolved open questions aren't propagated to referencing sections, body sections duplicate from body-surgery append failures.

**Action:** Refine now includes a self-consistency check, and Boss treats internal contradictions as NOT_READY. A future automated contradiction checker could make this structural instead of review-driven.

---

## P-57: Error and rollback paths consistently omitted from specs

**First observed:** 2026-03-06 (cross-critique entries)
**Promoted:** 2026-04-04
**Occurrences:** ~5 entries (low frequency but critical impact)
**Status:** Addressed on the spec path — `prd-validate.sh`, PM template, and Boss review now block missing failure/recovery coverage for state-changing work

Specs for state-changing operations (status transitions, deployments, merges, DB mutations) describe the happy path but omit what happens when the operation fails mid-way. Left-behind state, recovery procedures, and rollback behavior are unspecified.

**Action:** PM specs now include a dedicated failure/recovery section, `prd-validate.sh` fails state-changing specs that omit it, Boss treats the omission as NOT_READY, and refine still checks for error/rollback coverage during artifact cleanup.

---

## P-58: Never delete a stray Yoke DB before migrating its contents

**First observed:** 2026-04-11 (YOK-1373 Phase E/F cleanup incident; filed as YOK-1379)
**Promoted:** 2026-04-11
**Occurrences:** 1 catastrophic instance (so far) — 4095 irrecoverable session/scheduler rows destroyed
**Status:** Addressed at the time with a worktree-aware write-path resolver and stray-DB doctor guards. Superseded: the control plane is now Postgres-native and worktree-local DB files are refused at the connection boundary. The general rule — never destroy un-inventoried state — stands.

A path-resolution bug in `yoke/api/domain/backlog.py` (YOK-1379) caused backlog writes from a linked worktree to silently open `.worktrees/<branch>/yoke/yoke.db`. SQLite `connect()` created the file on first write, minted a new `YOK-1` from the empty `items` table, and the GitHub sync path wired that phantom row to the real historic `YOK-1` issue (`#37`). During YOK-1373 cleanup the discovering agent **deleted the stray DB without migrating its contents first** — wiping 4095 rows of genuine telemetry (`SessionRegistered`, `DependencyGateEvaluated`, `FrontierComputed`, `WorkClaimed`, `FrontierStepSelected`, `WorkReleased`, `SessionEnded`, `StaleSessionReclaimed`, …). That data is unrecoverable.

The rule derived from this incident:

1. A stray Yoke DB is **not** disposable just because it's in the wrong location. Its rows may be the only evidence of real session/scheduler activity.
2. Never `rm`, `git clean`, or otherwise destroy a non-empty stray `yoke.db` file. Treat it like production state that ended up in the wrong directory.
3. Migrate contents into the canonical main-repo DB **before** deletion, inside a single transaction, failing loud on any conflict rather than silently skipping rows.
4. Deletion is only safe after the migration summary has been reviewed by the operator.

**Action (at the time; this machinery was retired with the Postgres cutover):** backlog path resolution was rewired onto a worktree-aware resolver; the create path failed loud on missing or 0-byte DBs outside explicit bootstrap mode; a stray-DB doctor check surfaced both repo-root and worktree-local strays; plain `doctor --fix` refused non-empty strays; and an opt-in confirmation-gated path ran a transactional per-table merge that aborted on any conflict and only removed the stray on success. The 2026-04-11 telemetry loss is a permanent negative example — reference P-58 whenever anyone proposes blanket `rm` as a cleanup fix for "stray" state they haven't inventoried.
