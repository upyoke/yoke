# Yoke Agent Telemetry — Frequency Table & Recipe Pain Map (v2)

**Window:** 14 days (2026-05-07 → 2026-05-20)
**Data source:** `events` table (`HarnessToolCallCompleted` + `HarnessToolCallDenied` + `HarnessToolCallFailed` × `tool_name='Bash'`)
**Skill attribution:** correlated subquery against `NextActionChosen.scheduler.next_step` per session_id — the most recent skill directive before each Bash call. **More reliable than `harness_sessions.mode`** which carries the session's current (stale) mode rather than event-time skill state.
**Invoker:** `events.agent` column (null = main_session).

## Open Issues with the Telemetry Itself

- **O-1: Per-subagent denial attribution is missing.** All 2,200 `HarnessToolCallDenied` events in the 14-day window record `agent=NULL` regardless of whether the call was from main session or a subagent. PreToolUse hooks either fire from main-session context even when dispatching to a subagent, or the event-emit layer doesn't capture agent. This makes per-subagent denial counts invisible. Section E reports aggregate denial counts only; per-invoker denial split is intentionally omitted until the attribution gap is fixed.
- **O-2: Skill attribution still has a `no-prior-action` bucket** (~38k events) where no `NextActionChosen` fired before the Bash call in the same session. These are mostly fresh-session work or talmud activity outside any skill. They're a legitimate category, not a data error.
- **O-3: `harness_sessions.mode` is not reliable as a skill signal** — it lags real workflow state and aggregates aggressively. `mode='advance'` covers worktree-entry, implementation, review, polish. `mode='wait'` is a catch-all. `NextActionChosen.scheduler.next_step` is the better signal and is used throughout this report.

---

## Section A — The 30,000-foot view

**Total Bash tool calls (14d): ~127,500**

| Invoker | Tool calls | % of total | What it does |
|---|---|---|---|
| **main_session** | 111,800 | 87.7% | Everything top-level — talmud, freeform, all `/yoke` skills run from main |
| **engineer** subagent | 11,300 | 8.9% | Dispatched from `/yoke conduct`; implements one epic task |
| **tester** subagent | 3,200 | 2.5% | Dispatched from `/yoke conduct`; reviews epic task |
| **simulator** subagent | 1,040 | 0.8% | Dispatched from `/yoke shepherd`; read-only execution-trace simulation |
| **architect** subagent | 565 | 0.4% | Dispatched from `/yoke shepherd`; plan authoring |
| **product-manager** subagent | 59 | <0.1% | Spec authoring assist (rare) |
| **boss** subagent | 29 | <0.1% | Gate verdict reviews (rare) |

**Volume ≠ priority.** 87% from main session means main-session recipes get the most usage, but engineer at 11.3k calls / 14d is **806 calls per day** — plenty to justify dedicated engineer-bound recipes. Each invoker is analyzed separately below.

**Main session by attributed skill (via NextActionChosen):**

| Skill | Main-session Bash calls | % of main session |
|---|---|---|
| no-prior-action (talmud / fresh session) | 33,112 | 29.6% |
| `/yoke advance` | 14,261 | 12.8% |
| `/yoke polish` | 13,771 | 12.3% |
| `/yoke refine` | 10,650 | 9.5% |
| `/yoke usher` | 6,466 | 5.8% |
| `/yoke conduct` (orchestrating engineers/testers) | 3,402 | 3.0% |
| `/yoke shepherd` | 953 | 0.9% |
| Other / between-skills | ~29,000 | ~26% |

**Subagents by attributed skill (the workflow that dispatched them):**

| Subagent | Skill context (top) | % |
|---|---|---|
| engineer | `conduct` 6,259 (84%) / `no-prior-action` 740 / `advance` 79 | engineer = epic-task implementation |
| tester | `conduct` 2,115 (87%) / `no-prior-action` 322 | tester = epic-task review |
| simulator | `shepherd` 598 (66%) / `conduct` 97 / `no-prior-action` 231 | simulator = plan-time trace |
| architect | `shepherd` 265 (64%) / `no-prior-action` 150 | architect = plan authoring |
| boss | `no-prior-action` 29 (100%) | boss = ad-hoc gate verdicts |

**Top-level conclusion:** Recipe authoring needs to consider FOUR distinct execution shapes:
1. **Main session in a named skill** (`advance`, `polish`, `refine`, `usher`, `conduct`, `shepherd`) — 49k calls
2. **Main session NOT in a named skill** (no-prior-action + between-skills) — ~62k calls. **Larger than any single skill.**
3. **Engineer/Tester inside `conduct`** — 8.4k subagent calls
4. **Architect/Simulator inside `shepherd`** — 863 subagent calls

The "main session outside any skill" bucket (#2) is the BIGGEST — agents do enormous amounts of ad-hoc work in talmud / freeform. Universal-tier recipes are the highest-leverage authoring target.

---

## Section B — Per-Invoker Top Commands

Each invoker analyzed separately. Percentages are within that invoker's own call volume.

### B-1. main_session top verbs (111,800 calls)

| Verb | Count | % of main |
|---|---|---|
| other / uncategorized | 12,107 | 10.8% |
| `sed read` (skill/doc files) | 11,913 | 10.7% |
| `grep/rg` codebase search | 10,068 | 9.0% |
| `git` inspect | 8,145 | 7.3% |
| `db_router items get` | 7,289 | 6.5% |
| `env-prefix` (`YOKE_*=… python …`) | 6,424 | 5.7% |
| `db_router query "SELECT …"` | 4,775 | 4.3% |
| `mktemp+capture` (capture-first discipline) | 3,373 | 3.0% |
| `wc -l` (file size check) | 2,093 | 1.9% |
| `python3 -c inline` | 1,496 | 1.3% |
| `watch_pytest *` | 1,226 | 1.1% |
| `cd+chain` | 1,202 | 1.1% |
| `sc path-claim-*` (all variants) | 1,052 | 0.9% |
| `db_router epic` | 929 | 0.8% |
| `ls` | 725 | 0.6% |
| `db_router shepherd` | 685 | 0.6% |
| `worktree paths` | 620 | 0.6% |
| `echo` | 582 | 0.5% |
| `db_router items update` | 570 | 0.5% |
| `cat` | 530 | 0.5% |
| `harness_sessions` who-claims | 516 | 0.5% |
| `db_router events` | 508 | 0.5% |
| `sc session-* *` (heartbeat/checkpoint/touch/end/offer) | 431 | 0.4% |
| `sc claim-work` | 426 | 0.4% |
| `sc release-work-claim` | 401 | 0.4% |
| `python3 - heredoc` | 391 | 0.3% |
| `command_definitions get yoke full\|quick` | 322 | 0.3% |
| `watch_merge *` | 318 | 0.3% |
| `session_execution_scope` | 306 | 0.3% |
| `watch_doctor *` | 268 | 0.2% |

**Main-session profile:** discovery (sed + grep + git inspect = ~30% of calls) + state lookup (items get + query + items update + epic + sections = ~13%) + scaffolding (env-prefix + mktemp + watch wrappers = ~10%) + lifecycle (claim+release+session-* = ~1.5%). Mutations are tiny. **The recipe lever is in discovery and scaffolding, not in mutations.**

### B-2. engineer subagent top verbs (11,300 calls)

| Verb | Count | % of engineer |
|---|---|---|
| **`cd+chain`** | **3,185** | **28.2%** |
| `grep/rg` | 1,220 | 10.8% |
| `git` | 684 | 6.0% |
| other | 388 | 3.4% |
| `wc -l` (file size check) | 369 | 3.3% |
| `db_router query` | 259 | 2.3% |
| `db_router epic` (progress notes / status) | 220 | 1.9% |
| `watch_pytest *` (foreground) | 117 | 1.0% |
| `ls` | 117 | 1.0% |
| `python3 -c inline` | 104 | 0.9% |
| `db_router items get` | 80 | 0.7% |
| `sc path-claim-widen` | 64 | 0.6% |
| `watch_doctor *` | 44 | 0.4% |
| `echo` | 42 | 0.4% |
| `cat` | 32 | 0.3% |
| `sc path-claim-list` | 28 | 0.2% |
| `mktemp+capture` | 22 | 0.2% |
| `file_line_check` | 16 | 0.1% |
| `python3 - heredoc` | <10 | — |
| `sc claim-work` / `release-work-claim` | 2+2 | negligible |

**Engineer profile:** **`cd+chain` dominates at 28% of all engineer Bash calls.** That's by far the largest single recipe-target in any subagent role. The pattern is `cd /Users/.../.worktrees/YOK-X && python3 -m runtime.api...` because (a) Bash subshells lose cwd between calls and (b) the `lint_session_cwd` checks fall back to harness cwd when no path target extracts. Engineer also doesn't use `mktemp+capture` much (only 22 calls vs main session's 3,373) — engineers run foreground per the subagent rule, so capture-first wrappers are less needed. Engineer's mutation work (`sc claim-work` = 2, `sc release-work-claim` = 2, `db_router items update` = 3) is essentially zero — engineer authors via `db_router epic` (progress notes) and the orchestrator does the lifecycle transitions.

### B-3. tester subagent top verbs (3,200 calls)

| Verb | Count | % of tester |
|---|---|---|
| **`cd+chain`** | **1,018** | **31.8%** |
| `grep/rg` | 407 | 12.7% |
| `db_router epic` (review-seed/insert/get) | 187 | 5.8% |
| other | 176 | 5.5% |
| `git` | 150 | 4.7% |
| `watch_pytest *` (foreground) | 71 | 2.2% |
| `db_router query` | 66 | 2.1% |
| `wc -l` | 61 | 1.9% |
| `python3 -c inline` | 59 | 1.8% |
| `mktemp+capture` | 45 | 1.4% |
| `ls` | 39 | 1.2% |
| `echo` | 39 | 1.2% |
| `cat` | 32 | 1.0% |
| `watch_doctor *` | 21 | 0.7% |
| `db_router items get` | 13 | 0.4% |
| Others | <10 each | — |

**Tester profile:** **Same `cd+chain` dominance as engineer (31.8%).** Same root cause. Beyond that, tester is heavily review-focused: `grep/rg` to find evidence, `db_router epic` for verdict CRUD, foreground `watch_pytest` to confirm tests pass. Tester mutations are essentially zero (1 `claim-release`, 1 `path-claim-register` in 14 days).

### B-4. simulator subagent top verbs (1,040 calls)

| Verb | Count | % of simulator |
|---|---|---|
| `grep/rg` | 339 | 32.6% |
| `db_router epic` | 184 | 17.7% |
| **`cd+chain`** | **80** | **7.7%** |
| `db_router query` | 72 | 6.9% |
| `db_router items get` | 72 | 6.9% |
| `ls` | 41 | 3.9% |
| `python3 -c inline` | 26 | 2.5% |
| `domain.epic` | 24 | 2.3% |
| `wc -l` | 22 | 2.1% |
| other | 16 | 1.5% |
| `git` | 15 | 1.4% |
| `sed read` | 10 | 1.0% |
| `echo` | 10 | 1.0% |
| `db_router shepherd` | 6 | 0.6% |
| `sc path-claim-list` | 4 | 0.4% |
| Others | <5 each | — |

**Simulator profile:** Pure read. Heavy `grep/rg` for code-trace work. `db_router epic` and `domain.epic` for shepherd-time task inspection. Zero mutations. **`cd+chain` is lower for simulator (7.7%)** — likely because simulator operates on a plan-stage epic before any worktree exists; it doesn't need to cd into a worktree to do its work.

### B-5. architect subagent top verbs (565 calls)

| Verb | Count | % of architect |
|---|---|---|
| `grep/rg` | 163 | 28.8% |
| `db_router epic` | 55 | 9.7% |
| `db_router items get` | 51 | 9.0% |
| `ls` | 46 | 8.1% |
| `wc -l` (File Budget audit) | 25 | 4.4% |
| other | 16 | 2.8% |
| `db_router query` | 13 | 2.3% |
| `python3 -c inline` | 8 | 1.4% |
| `cat` | 7 | 1.2% |
| `sc path-claim-list` | 6 | 1.1% |
| `db_router shepherd` (dep-list) | 6 | 1.1% |
| `sed read` | 3 | — |
| `domain.sections` | 3 | — |
| `domain.epic` | 3 | — |
| `sc path-claim-widen` | 2 | — |
| `db_router items update` | 2 | — |
| `sc claim-work` / `release-work-claim` | 1+1 | — |
| Others | 1 each | — |

**Architect profile:** Plan-stage work — read items get / shepherd dependency-list / epic task-get-body, search code via `grep/rg`, audit File Budget via `wc -l`, register path claims via `sc path-claim-*`. Mutations are tiny (1 claim-work, 2 items update). **No `cd+chain` AT ALL** — architect works against the plan, not a worktree.

### B-6. boss subagent + product-manager (88 calls combined)

| Invoker | Verb | Count |
|---|---|---|
| boss | `db_router items get` | 10 |
| boss | `db_router epic` | 8 |
| boss | `db_router query` | 6 |
| boss | `sc path-claim-list` | 2 |
| product-manager | (insufficient volume to characterize) | 59 |

**Boss profile:** Pure read; gate verdicts. PM volume is too low to characterize. **Neither warrants dedicated recipe coverage at current volume.**

---

## Section C — Per-Invoker Recipe Pain Map

Top-3 friction recipes per invoker, ranked by % of that invoker's call volume:

| Invoker | #1 pain | #2 pain | #3 pain |
|---|---|---|---|
| **main_session** | `sed read` of skill/doc files (10.7% — discovery tax) | `grep/rg` (9.0%) | `db_router items get` placeholder-heavy recipe (6.5%) |
| **engineer** | **`cd+chain` (28.2%) — fix with `git -C` / `--rootdir` recipe** | `grep/rg` (10.8%) | `wc -l` File Budget check (3.3%) |
| **tester** | **`cd+chain` (31.8%) — same fix as engineer** | `grep/rg` (12.7%) | `db_router epic` review-insert sequence (5.8%) |
| **simulator** | `grep/rg` (32.6% — codebase trace work) | `db_router epic` (17.7%) | `db_router query` (6.9%) |
| **architect** | `grep/rg` (28.8%) | `db_router epic` task-get-body (9.7%) | `db_router items get` plan fields (9.0%) |
| **boss + PM** | n/a — insufficient volume | | |

**The `cd+chain` pattern is the highest-leverage subagent recipe by far.** Engineer + tester together do **4,203 cd-chains in 14 days** — 300/day. A single recipe teaching `git -C <abs>`, `--rootdir <abs>`, and the in-flag worktree pattern (already supported by `lint_session_cwd_target_extract.py`) would directly eliminate the majority.

---

## Section D — Per-Skill Activity (via NextActionChosen attribution)

Bash call counts attributed by skill, split by invoker. Skill = the most recent `NextActionChosen.scheduler.next_step` event before the Bash call's timestamp.

| Skill | Main | Engineer | Tester | Simulator | Architect | Boss | Total |
|---|---|---|---|---|---|---|---|
| **no-prior-action** (talmud / fresh) | **33,112** | 740 | 322 | 231 | 150 | 29 | **34,584** |
| **`/yoke advance`** | 14,261 | 79 | 0 | 0 | 0 | 0 | 14,340 |
| **`/yoke polish`** | 13,771 | 0 | 0 | 0 | 0 | 0 | 13,771 |
| **`/yoke refine`** | 10,650 | 0 | 0 | 0 | 0 | 0 | 10,650 |
| **`/yoke usher`** | 6,466 | 0 | 0 | 0 | 0 | 0 | 6,466 |
| **`/yoke conduct`** | 3,402 | **6,259** | **2,115** | 97 | 0 | 0 | 11,873 |
| **`/yoke shepherd`** | 953 | 0 | 0 | **598** | **265** | 0 | 1,816 |
| Other / between-skills | ~29,000 | ~4,200 | ~760 | ~110 | ~150 | 0 | ~34,000 |

**Key recipe-priority readings:**

1. **`no-prior-action` (talmud) is the largest single bucket** — 34,584 calls. Universal-tier recipes (cancel/transition, claim-mutate-release, capture-first, git inspect, db_router query) must be discoverable WITHOUT a named skill context. They go in the universal packet.

2. **`/yoke advance` and `/yoke polish` are the next two biggest** — 14k and 13.7k main-session calls each. The advance/polish workflow does a lot of work in main session (worktree entry, file edits, capture-first commands, etc.). Recipes for these flows have high leverage.

3. **`/yoke conduct` is the only skill where subagents do substantial work** — 6,259 engineer + 2,115 tester. Conduct-mode recipes naturally split: orchestrator-side recipes (main: 3,402 calls — dispatching, awaiting, status) vs subagent-side recipes (engineer + tester: 8,374 calls — implementation + review).

4. **`/yoke shepherd` is a subagent-heavy skill at the architect/simulator layer** — 598 + 265 = 863 calls. Low volume but high specificity. Worth dedicated shepherd-mode subagent recipes for plan authoring.

5. **`/yoke refine` is main-session-only** — 10,650 calls, zero subagents. Refine recipes belong in the main-session packet.

6. **`/yoke usher` is main-session-only** — 6,466 calls. Same as refine — main-session merge/deploy recipes only.

---

## Section E — Denials by Lint Rule (aggregate only — see O-1)

Note: per-invoker denial split is omitted because of telemetry gap O-1 (above).

| Lint rule | 14-day denials | What it catches | Recipe angle |
|---|---|---|---|
| `lint-shell-quoted-function-payload` | **1,524** | Shell-constructed function-call envelopes | Anti-pattern doctrine + HTTP/CLI-adapter recipes |
| `lint-subagent-background` | 255 | Subagent using Bash(run_in_background) + Monitor | Subagent foreground watcher recipe |
| `lint-long-command-polling` | 236 | Polling on capture file while command runs | Main-session Monitor pair recipe |
| `lint-sqlite-cmd` | 122 | Direct `sqlite3 <db>` | `db_router query` recipe |
| `lint-claim-ownership-mutations` | 14 | Mutation without claim | Claim-mutate-release sequence recipe |
| `lint-main-commit` | 14 | Commit on main | Worktree recipe |
| `lint-structured-field-transform-shell` | 12 | Shell choreography on structured fields | `item_field_transform` recipe |
| `lint-destructive-git` | 10 | `git reset --hard` etc. | (operator discipline, not recipe) |
| `lint-python-runtime-import-in-tmp` | 2 | `/tmp/*.py` with `from runtime.*` | In-tree script recipe |

**Aggregate total: 2,189 denials in 14 days.** The single biggest class (`lint-shell-quoted-function-payload`) is ~70% of total denial volume.

---

## Section F — Sequence Patterns (multi-call workflows)

Inferred from invoker activity profiles. Frequency is approximate per-day rate.

| Sequence ID | Pattern | Daily rate (14d) | Invoker | Tier |
|---|---|---|---|---|
| S-01 | claim-work → items update → release-work-claim | ~29/day | Main | **Tier 1** |
| S-02 | mktemp → command > tmp 2>&1 → tail -80 | ~241/day | Main | **Tier 1** |
| S-03 | cd worktree → python3 -m runtime.api... | ~300/day | Engineer+Tester | **Tier 1 (subagent-bound)** |
| S-04 | items get → edit → items update --stdin | ~40/day | Main (refine) | Tier 2 |
| S-05 | watch_pytest pair → Bash bg + Monitor → tail | ~88/day | Main | **Tier 1** |
| S-06 | git status → git log → gh run list | ~51/day | Main | Tier 1 |
| S-07 | YOKE_IDEA_INTAKE=1 db_router items add | ~4/day | Main (idea) | Tier 1 |
| S-08 | epic task-get-body → review-insert → review-get | ~3/day | Tester | Tier 2 |
| S-09 | path-claim-register → path-claim-widen | ~31/day | Main (advance) | Tier 2 |
| S-10 | watch_merge pair → Monitor → gh run list | ~23/day | Main (usher) | Tier 2 |
| S-11 | engineer dispatch → engineer progress → engineer done → tester review | ~150/day | Main (conduct) + subagents | Tier 2 |

---

## Section G — Tier 2 / Tier 3 Skill-Bound Recipe Inventory

### Tier 2 — Skill-Bound

**For `/yoke advance` (14k main calls):**
- Worktree entry sequence
- Path-claim register with planned-files (S-09)
- Engineer-side prep (items get spec → file_line_check)

**For `/yoke polish` (13.7k main calls):**
- Worktree simplify pass
- Polish verification (re-run tests via watch_pytest, doctor --quick)

**For `/yoke refine` (10.7k main calls):**
- Structured-field edit via `items.structured_field.replace` (S-04)
- Progress Log append via HTTP

**For `/yoke usher` (6.5k main calls):**
- watch_merge sequence (S-10)
- Post-merge CI inspection (gh run list)

**For `/yoke conduct`:**
- Orchestrator side: dispatch + status check (3.4k main calls)
- Engineer subagent: foreground watch_pytest, progress note append, `wc -l` File Budget audit
- Tester subagent: review-seed → review-insert → review-get (S-08)

**For `/yoke shepherd`:**
- Architect subagent: shepherd dependency-add, items get plan fields
- Simulator subagent: epic task-list, code-trace `rg` patterns

### Tier 3 — On-Demand / Operator-Only (referenced in docs, not in packet)

- Foreign-claim override (`sc claim-release`) — operator-only, monthly
- `path-claim-narrow` — 20 main + 1 each subagent in 14d
- Stranded coordination-lease release
- DB-claim amendment edge cases (declared form with full payload)

---

## Section H — Gap Map: Top Frequency vs Current Packet Coverage

| Top-frequency activity | 14d count | Currently in packet? | Quality |
|---|---|---|---|
| `db_router items get` (main) | 7,289 | Yes (`_commands_core.py:14-34`) | Placeholder `YOK-N`, 601-char notes |
| `db_router query` (all invokers) | 5,165 | Yes (`_commands_core.py:313-318`) | One-liner, no canonical SELECTs |
| `cd+chain` (engineer+tester) | 4,203 | **NO** | **Missing — top Tier 1 subagent recipe** |
| `mktemp+capture` (main) | 3,373 | NO (in CLAUDE.md prose) | **Missing — codify** |
| `watch_pytest` (all) | 1,414 | NO (in CLAUDE.md prose) | **Missing — codify** |
| `db_router epic` (eng+tester+arch+sim) | 1,648 | Partial (`_commands_core.py:170-213`) | Has placeholders |
| `sc claim-work` + `release-work-claim` (main) | 827 | Yes (`_commands_claims.py`) | Two separate entries, not sequence |
| `sc session-*` (main) | 431 | **NO** | **Missing** |
| `sc path-claim-list` | 449 | Yes (`_commands_claims.py:124-131`) | One-line recipe with no use case |
| `sc path-claim-widen` | 384 | Yes (`_commands_claims.py:172-191`) | 698-char notes, recipe is 240 chars |
| `watch_merge` | 318 | **NO** | **Missing** |
| `watch_doctor` | 333 | **NO** | **Missing** |
| `command_definitions get` | 322 | NO (auto-loaded) | Probably not needed as recipe |
| `sc db-claim-amend` | 173 | Yes (`_commands_core.py:152-167`) | 116 denials wrapping it — needs anti-pattern callout |
| `item_field_transform` | 223 | Yes (`_commands_core.py:63-75`) | API-first only; CLI sequence missing |
| `sc path-claim-narrow` | 22 | NO | Tier 3 |

---

## Section K — Guardrail Review (lint tuning candidates)

Issues surfaced during this analysis where lint behavior creates friction independent of recipe authoring. These need lint-tuning tickets, not packet recipes.

### G-01: `lint-session-cwd` over-eager empty-target denials

**Severity:** High. **Volume:** 518 / 684 (76%) of `SessionCwdMismatchDenied` events in 14 days.

**Pattern:** When a Bash call has no extractable target path (e.g. `db_router query "SELECT ..."`, `service_client --help`, `harness_sessions who-claims YOK-N`), `lint_session_cwd.py` falls back to denying based on the harness's current cwd alone. These are read-only / self-orientation calls that touch no file — denying them based on cwd is over-eager and contradicts the CLAUDE.md `## Yoke Authority — Hard Rule` doctrine that read-only self-orientation is always allowed.

**Bucket breakdown (14d):**
- empty-target (cwd-only): 518 (76%)
- regex/placeholder false positives: 28 (4%)
- real worktree-path outside claim: 36 (5%) — legitimate denials, leave alone
- in-repo paths outside claim: 7 (1%) — legitimate
- tmp-path / other: ~95 (14%)

**Proposed fix:** Allow tool calls when `extract_payload_targets` returns empty AND the command matches a known read-only signature (`db_router query "SELECT…"`, `*-list`, `*-get`, `*-conflicts`, `--help`, `who-claims`, `git status`, `git log`, etc.). The patterns are already enumerable from the lint codebase.

**Chip spawned:** filed via mcp__ccd_session__spawn_task at 2026-05-20 — ticket creation through `/yoke idea`.

### G-02: `lint_session_cwd_target_extract` false positives on path-like strings

**Severity:** Low. **Volume:** 28 / 684 (4%) of `SessionCwdMismatchDenied` events in 14 days.

**Pattern:** The absolute-path positional argument extractor catches strings that LOOK like paths but aren't: sed regexes (`/^## Warnings/`), URL paths (`/v1/items`), test glob patterns (`/test_`), human placeholders (`YOK-N` interpreted as `/N`).

**Proposed fix:** Require the candidate string to actually parse as a real filesystem path before treating it as a target. Reject strings containing regex metacharacters (`^`, `$`, `*`, `?`, `{`, `}`), URL-like patterns (`/v\d+/`), or `:` mid-string.

**Bundle with G-01 fix** since both touch the same lint module.

### G-03: Per-subagent denial attribution is missing (telemetry gap)

**Severity:** Telemetry coverage issue (not a lint bug). **Volume:** all 2,200 denial events in 14 days.

**Pattern:** Every `HarnessToolCallDenied` event records `agent=NULL`. PreToolUse hooks either fire from main-session context even when dispatching to a subagent, or the event-emit layer doesn't capture agent. This means we can't measure whether subagent-specific recipes (e.g. `cd+chain` reduction) actually reduce subagent friction post-landing.

**Proposed fix:** Capture `YOKE_HOOK_AGENT_TYPE` env var (already set by subagent adapters for the subagent-background lint) into denial event envelopes. The data is available; the emit layer just isn't recording it.

**File a separate ticket** — telemetry-coverage work, no lint behavior change. Defer until G-01 lands.

---

## Section L — Headline Numbers (v2)

- **127,500** Bash calls in 14 days
- **87.7%** main session, **12.3%** subagents (analyzed separately)
- **34,584** calls (27%) in `no-prior-action` (talmud) — **the largest single bucket**, larger than any named skill
- **49,503** calls (39%) attributed to a named `/yoke` skill via NextActionChosen
- **`cd+chain`** = **28.2% of engineer + 31.8% of tester** — single highest subagent-bound friction
- **4,203** total cd-chain calls — wholly replaceable with `git -C` / `--rootdir`
- **1,524** denials on `lint-shell-quoted-function-payload` — 70% of all denials
- **518** denials on `lint-session-cwd` empty-target (76% of cwd-denials are over-eager — chip filed)
- **3,373** capture-first wrappers — already the dominant pattern; needs codification
- **11,913** `sed -n '1,Np' <doc>` calls — discovery tax
- **832** claim+release lifecycle calls (main) — most-touched mutation triplet
- **49** registered function ids; only ~12 have a CLI adapter taught in the packet today

---

*Generated 2026-05-20 from `events` table via `python3 -m yoke_core.cli.db_router query`. Methodology: skill attribution via correlated subquery against `NextActionChosen` events (most recent before each Bash call within session). v2 redoes per-invoker as separate populations (not collapsed), adds Section K guardrail review.*


---

## Section M — AC-7 Pre-Landing Baseline (YOK-1819)

Captured 2026-05-21 against the events table over the prior 14-day window. AC-8 will rerun these same queries 14 days after YOK-1819 lands on main to measure the impact of the AC-2 help-text repair + AC-4 contract lints + AC-5 stance + AC-1 packet recipes.

**M-1. `service_client --help` invocations on the 8 covered subcommands (14d):**
- Aggregate: **286** invocations of any `service_client --help` shape on the covered subcommand set (claim-work / path-claim-register / path-claim-widen / items get / items query / items update / who-claims / umbrella).
- Top shapes: `path-claim-widen --help` 55, `claim-work --help` 46, `items update --help` 44 (multiple capture-pipe variants), `path-claim-register --help` 26 (multiple capture-pipe variants), `items get --help` 4.
- AC-8 target: >=30% drop (<=200 in the 14-day post-landing window).

**M-2. `python3 -c "from runtime.api..."` invocations (14d):**
- Aggregate: **1,464** invocations of `python3 -c` shapes that import from `runtime.api`.
- AC-8 target: >=50% drop (<=732) once the `lint-no-agent-runtime-api-import-from-c` lint flips from `warn` to `deny` AND the agent-surface stance has been in agent context for 14 days.

**M-3. `curl localhost:8765` invocations (14d):**
- Aggregate: **72** invocations of `curl` shapes against `localhost:8765` / `127.0.0.1:8765` / `$YOKE_API`.
- AC-8 target: >=50% drop (<=36) once the `lint-no-agent-curl-against-yoke-api` lint flips from `warn` to `deny`.

**M-4. Lifecycle-transition tool-call counts (14d):**
- `ItemStatusChanged` events (canonical lifecycle transition signal): **1,839** in 14 days.
- `AdvancePhaseCompleted` events (per-phase signal -- preflight / worktree / environment / finalize): **493** in 14 days. The `/yoke advance` orchestrator emits one per phase, so 493 ~= ~123 advance entries assuming all four phases per run (a fair upper bound).
- AC-8 target: measurable drop in **per-advance Bash tool-call count**. The metric proxy is `Bash` calls within sessions that emit `ItemStatusChanged` divided by `ItemStatusChanged` count. Per-run drop is the goal; aggregate `ItemStatusChanged` count is expected to stay flat (the work itself is unchanged).

*Generated 2026-05-21 via `events` queries against CANONICAL_YOKE_DB. Stored under `docs/archive/legacy-plan-artifacts/atlas-boundary-inventory/atlas-evidence/` as source-controlled Gen 3 planning evidence.*
