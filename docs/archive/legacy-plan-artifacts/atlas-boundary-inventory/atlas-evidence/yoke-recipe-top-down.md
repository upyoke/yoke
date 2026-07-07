# Yoke Recipe Inventory — Top-Down First-Principles View

**Purpose:** Independent of telemetry. Walk the agent tree, enumerate what each agent/subagent conceptually needs to do at each workflow point, and list the recipes that should exist. Then cross-reference with the bottom-up telemetry analysis.

**Method:** Reading the agent ontology from CLAUDE.md, `/yoke` skills, and the substrate's role definitions. Listing recipes as 1-2 line sketches, not full multi-line authoring.

---

## Section A — The Agent Tree

```
YOKE ECOSYSTEM
│
├─ MAIN SESSION (Claude / Codex top-level)
│   The orchestrator. Runs every /yoke skill. Owns lifecycle
│   transitions. Owns GitHub sync. Dispatches subagents. Handles
│   freeform talmud activity outside any skill.
│
├─ SUBAGENT: engineer   (Bash, foreground only)
│   Dispatched from /yoke conduct. Implements one epic task end-to-end.
│   Owns: code edits, tests, progress notes, optional path-claim widen.
│
├─ SUBAGENT: tester     (Bash, foreground only)
│   Dispatched from /yoke conduct. Reviews engineer's work against ACs.
│   Owns: verdict authoring (review-seed → review-insert → review-get).
│
├─ SUBAGENT: architect  (Bash, foreground only)
│   Dispatched from /yoke shepherd. Authors the implementation plan.
│   Owns: epic-task split, inter-task dependencies, planned path claims.
│
├─ SUBAGENT: simulator  (Bash, foreground only, read-mostly)
│   Dispatched from /yoke shepherd. Traces execution across the plan
│   to identify cross-task integration risks. Read-only by design.
│
├─ SUBAGENT: boss       (Bash, foreground only)
│   Ad-hoc gate-verdict reviewer. Reads spec + evidence, emits pass/fail.
│
├─ SUBAGENT: product-manager  (Read/Grep/Glob only — no Bash)
│   Spec authoring assist. Reads ticket body + related items via Read.
│
└─ SUBAGENT: product-designer (Read/Grep/Glob only — no Bash)
    UX spec authoring assist. Reads item body + existing UI components.
```

**Key constraint from CLAUDE.md:** Subagents are *atomic-turn*. They must run long commands foreground in a single Bash call. They MUST NOT use `Bash(run_in_background)` + `Monitor`. PM and PD have no Bash at all.

---

## Section B — Workflow Map: What Each Agent Does, When

### B-1. Main Session

Main session runs in one of these contexts at any given time:

| Context | When | What main session is doing |
|---|---|---|
| **Talmud / freeform** | No active skill. Default state. | Ad-hoc investigation, exploration, freeform edits, talking to operator. |
| `/yoke idea` | New ticket intake | Dedup, create, author initial spec, register planned path claim |
| `/yoke refine` | Spec/plan iteration | Read all fields, edit spec/technical_plan/File Budget, transition idea→refined-idea |
| `/yoke shepherd` | Epic plan authoring (epic-only) | Dispatch architect + simulator, author epic_tasks, transition planning→plan-drafted |
| `/yoke advance` | Open worktree | Create worktree, activate path claim, transition planned→implementing |
| `/yoke conduct` | Epic execution loop | Dispatch engineer → tester → next-task. Handle rework. |
| `/yoke polish` | Worktree finalize | Re-run pytest, doctor, simplify pass, transition →implemented |
| `/yoke usher` | Merge + deploy | watch_merge, wait CI, transition →release→done, deploy |
| `/yoke do` / `/yoke charge` | Frontier dispatch | Read NextAction, choose next, chain forward |
| `/yoke curate` | Ouroboros loop | Read entries, cluster, file follow-ups |

### B-2. Subagent contexts

| Subagent | Dispatched from | What it does |
|---|---|---|
| engineer | `/yoke conduct` (epic), `/yoke advance` (single-item) | Implement one epic task: read task body, edit code, run tests, file progress notes, commit |
| tester | `/yoke conduct` | Review engineer's task: read changed code + tests, run verification, file verdict |
| architect | `/yoke shepherd` | Author epic plan: split work into tasks, set ACs, dependencies, path claims |
| simulator | `/yoke shepherd` | Trace execution paths across plan; emit integration-risk findings |
| boss | Ad-hoc / any gate | Read item, evidence, ACs; emit pass/fail verdict |
| product-manager | `/yoke shepherd` (spec phase) | Author spec via PRD discipline |
| product-designer | `/yoke shepherd` (design phase) | Author design_spec UX shape |

---

## Section C — Recipe Inventory (top-down)

### C-1. Universal Recipes (every Bash-capable agent + main session)

These are the foundational operations that show up everywhere. If an agent can't do these in one paste, they will burn calls discovering.

| ID | Recipe | What it does |
|---|---|---|
| U-1 | Resolve session_id + actor_id | Read both from `$YOKE_SESSION_ID` env + db_router query into env vars |
| U-2 | Read item state (single ticket) | `items get YOK-N <field>` and `items get YOK-N body --section "## X"` |
| U-3 | Read claim state | `harness_sessions who-claims YOK-N` |
| U-4 | Read recent events on a ticket | `db_router events list --item-id N --limit 20` |
| U-5 | Resolve GitHub issue from YOK-N | `items get YOK-N github_issue` → strip leading `#` |
| U-6 | Capture-first wrapper | `_tmp=$(mktemp); cmd > "$_tmp" 2>&1; tail -80 "$_tmp"` |
| U-7 | Worktree-respectful execution | `git -C <abs>`, `--rootdir <abs>`, `--worktree-path <abs>` — NO `cd + chain` |
| U-8 | Git state inspect (3-line orientation) | `git status --short --branch` + `git log --oneline -20` + `gh run list --branch main --limit 1` |
| U-9 | SQL self-orientation queries | Top 5 canonical SELECTs: open work, my claims, recent merges, frontier, item history |
| U-10 | Log ouroboros entry (failure or discovery) | `service_client ouroboros-log --kind {failed,new,changed} --recipe-id X --evidence /tmp/log` |
| U-11 | List registered function ids | `curl http://127.0.0.1:8765/v1/functions/registry` OR Python list_entries() |
| U-12 | Dispatch any function call via HTTP | curl POST to `/v1/functions/call` with envelope (covers all 49 function ids) |

### C-2. Main-Session Mutation Recipes (orchestrator-side, NOT subagent)

| ID | Recipe | What it does |
|---|---|---|
| M-1 | Cancel/stop/fail a ticket | claim-work → items update status → release-work-claim |
| M-2 | Forward status transition | Same triplet, non-terminal target status |
| M-3 | Acquire/release work claim (CLI) | `sc claim-work --item YOK-N --reason X` and inverse |
| M-4 | Append Progress Log entry | HTTP dispatch of items.progress_log.append (read-merge-write atomic) |
| M-5 | Replace a structured field | HTTP dispatch of items.structured_field.replace |
| M-6 | Section upsert / append | HTTP dispatch of items.section.upsert / items.structured_field.section_upsert |
| M-7 | Register path claim | `sc path-claim-register --item YOK-N --paths X,Y,Z [--allow-planned]` |
| M-8 | Widen path claim | `sc path-claim-widen <claim-id> --paths A,B [--allow-planned]` |
| M-9 | Narrow path claim | `sc path-claim-narrow <claim-id> --drop-paths X` or `--keep-paths Y` |
| M-10 | Add item dependency | `db_router shepherd dependency-add <dep> <blk> idea --gate-point X --rationale Y` |
| M-11 | DB-claim amend (negative-default) | `sc db-claim-amend --item YOK-N --reason X --state none` |
| M-12 | DB-claim amend (declared) | Same with `--payload -` and JSON envelope on stdin |
| M-13 | Idea-intake create item | `YOKE_IDEA_INTAKE=1 db_router items add --project yoke ...` |
| M-14 | Operator override (foreign claim release) | `sc claim-release --item YOK-N --claim-id X --reason Y` |
| M-15 | Rebuild board | `sc backlog-cli rebuild-board` |

### C-3. Watcher Recipes (long-running commands)

| ID | Recipe | What it does |
|---|---|---|
| W-1 | watch_pytest main-session (bg + Monitor) | `--print-streaming-pair` → paste pair into Bash(bg) + Monitor |
| W-2 | watch_pytest subagent (foreground) | Direct invocation, no `--print-streaming-pair`, blocks within one tool call |
| W-3 | watch_doctor main-session (bg + Monitor) | Same pair pattern for `--quick` / `--full` / `--only` |
| W-4 | watch_doctor subagent (foreground) | Same direct invocation |
| W-5 | watch_merge main-session | `--print-streaming-pair merge-worktree -- YOK-N` |
| W-6 | api_server lifecycle | `start` / `restart` / `stop` |

### C-4. Skill-Bound Main-Session Recipes

#### `/yoke idea` (main session)
| ID | Recipe | What it does |
|---|---|---|
| I-1 | Dedup search before creating | `sc backlog-cli dedup-search --query "..."` |
| I-2 | Create item (intake form) | Full M-13 with title, body, project, deployment_flow, type, priority |
| I-3 | Set architecture_impact | `db_router items update YOK-N architecture_impact uncertain\|none\|path_context_only\|architecture_model_change` |
| I-4 | Register planned path claim (intake) | M-7 with `--allow-planned` |

#### `/yoke refine` (main session)
| ID | Recipe | What it does |
|---|---|---|
| R-1 | Read all plan-stage fields | `items get YOK-N spec technical_plan worktree_plan` |
| R-2 | Edit spec via structured_field.replace | M-5 with field=spec |
| R-3 | Section upsert (ACs, File Budget, etc.) | M-6 with named heading |
| R-4 | Transition idea → refining-idea → refined-idea | M-2 twice |
| R-5 | DB-claim amend during refine | M-11 or M-12 |
| R-6 | Add Progress Log refine note | M-4 |

#### `/yoke shepherd` (main session, epic-only)
| ID | Recipe | What it does |
|---|---|---|
| Sh-1 | Dispatch architect subagent | `Agent` tool with subagent_type=yoke-architect |
| Sh-2 | Dispatch simulator subagent | Same with subagent_type=yoke-simulator |
| Sh-3 | Author epic_tasks (loop) | `db_router epic task-add E K --title T --body-file F` |
| Sh-4 | Transition refined-idea → planning → plan-drafted | M-2 twice |
| Sh-5 | Append shepherd_log finding | M-6 section upsert |
| Sh-6 | Author shepherd_caveats | M-5 with field=shepherd_caveats |

#### `/yoke advance` (main session)
| ID | Recipe | What it does |
|---|---|---|
| A-1 | Create worktree | `engines.advance create-worktree YOK-N` (or substrate equivalent) |
| A-2 | Activate path claim | (inferred — usually happens server-side on status transition) |
| A-3 | Transition planned → implementing | M-2 |
| A-4 | Enter worktree (the only allowed `cd`) | `cd /Users/.../.worktrees/YOK-N` once, for the session |

#### `/yoke conduct` (main session — orchestrator role)
| ID | Recipe | What it does |
|---|---|---|
| C-1 | Read epic plan + task list | `db_router epic task-list E` + `epic dispatch-chain-list E` |
| C-2 | Dispatch engineer for next task | `Agent` with subagent_type=yoke-engineer, full task envelope |
| C-3 | Dispatch tester after engineer done | `Agent` with subagent_type=yoke-tester |
| C-4 | Read engineer's progress notes | `db_router epic progress-note-list E` |
| C-5 | Read tester's verdict | `db_router epic review-get E K` |
| C-6 | Advance dispatch chain | `db_router epic dispatch-chain-advance E "YOK-N"` |
| C-7 | Update epic-task status | `db_router epic task-update-status E K <status>` |
| C-8 | Handle rework (rework_count) | `db_router epic task-update-field E K rework_count <N+1>` |

#### `/yoke polish` (main session)
| ID | Recipe | What it does |
|---|---|---|
| P-1 | Re-run pytest in worktree | W-1 with `--rootdir /Users/.../.worktrees/YOK-N` |
| P-2 | Re-run doctor | W-3 `-- --quick` |
| P-3 | File-line check (worktree diff) | `file_line_check check --base main` |
| P-4 | Worktree simplify pass | (manual review of diff via git log + git diff main..) |
| P-5 | Transition reviewed-implementation → polishing → implemented | M-2 twice |

#### `/yoke usher` (main session)
| ID | Recipe | What it does |
|---|---|---|
| U-USH-1 | Run merge-worktree (capture+monitor) | W-5 |
| U-USH-2 | Wait for GitHub CI | `gh run list --branch main --limit 1 --json status,conclusion --jq` polling |
| U-USH-3 | Transition implemented → release → done | M-2 twice |
| U-USH-4 | Run deploy engine | `engines.deploy <project>` |

#### `/yoke do` / `/yoke charge` (main session)
| ID | Recipe | What it does |
|---|---|---|
| D-1 | Read frontier | `curl http://127.0.0.1:8765/v1/charge/frontier` or `db_router shepherd next-action` |
| D-2 | Chain to next skill | (substrate-handled via `NextActionChosen` event) |

#### `/yoke curate` (main session)
| ID | Recipe | What it does |
|---|---|---|
| Cur-1 | Read ouroboros entries | `db_router query "SELECT * FROM ouroboros_entries WHERE ..."` |
| Cur-2 | Cluster + author follow-up | `/yoke idea` chain for each cluster |

### C-5. Subagent Recipes

#### engineer (in /yoke conduct, sometimes /yoke advance)
| ID | Recipe | What it does |
|---|---|---|
| E-1 | Read epic_task body | `db_router epic task-get-body E K` |
| E-2 | Read item context | `items get YOK-N spec technical_plan worktree_plan` |
| E-3 | Worktree-respectful pytest | W-2 with `--rootdir <abs>` or `cd worktree once` |
| E-4 | Worktree-respectful doctor | W-4 |
| E-5 | File-line check before commit | `file_line_check check --staged` |
| E-6 | Append epic-task progress note | `db_router epic progress-note-insert E K <num> --body-file PATH` |
| E-7 | Widen path claim (newly-discovered files) | M-8 with `--allow-planned` |
| E-8 | Commit with submission receipt format | Final progress note carries `---SUBMISSION-CHECKS-START---` / `END---` blocks |
| E-9 | Foreground capture-first for tests | Inline `watch_pytest -- runtime/api/test_X.py -q` blocks within one tool call |

#### tester (in /yoke conduct)
| ID | Recipe | What it does |
|---|---|---|
| T-1 | Read epic_task body + engineer's notes | `epic task-get-body` + `epic progress-note-list E` |
| T-2 | Read changed files in worktree | `git -C <worktree> log --oneline main..HEAD` + `git -C <worktree> diff main..HEAD --stat` |
| T-3 | Run pytest verification | W-2 |
| T-4 | Run doctor verification | W-4 |
| T-5 | Review-seed (if no row yet) | `db_router epic review-seed E K` |
| T-6 | Review-insert verdict | `db_router epic review-insert E K {pass\|fail} --body-file PATH` |
| T-7 | Review-get (verify) | `db_router epic review-get E K` |

#### architect (in /yoke shepherd)
| ID | Recipe | What it does |
|---|---|---|
| Ar-1 | Read item plan-stage fields | U-2 with spec, technical_plan, worktree_plan |
| Ar-2 | File-budget audit | `wc -l <planned-files>` to validate File Budget |
| Ar-3 | Author epic task | `db_router epic task-add E K --title T --body-file F` |
| Ar-4 | Add inter-task dependency | M-10 with `--gate-point activation\|coordination_only` |
| Ar-5 | Register planned path-claim | M-7 with `--allow-planned` |
| Ar-6 | Append to shepherd_log | M-6 section upsert with heading=shepherd findings |
| Ar-7 | Author shepherd_caveats | M-5 with field=shepherd_caveats |

#### simulator (in /yoke shepherd)
| ID | Recipe | What it does |
|---|---|---|
| Sim-1 | List epic tasks | `db_router epic task-list E` |
| Sim-2 | Read each task body | E-1 in loop |
| Sim-3 | Cross-task code trace | `rg -n "<symbol>" runtime/api/ --type py` |
| Sim-4 | Emit findings via section append | M-6 section append with heading="Simulation findings" |

#### boss (ad-hoc gates)
| ID | Recipe | What it does |
|---|---|---|
| B-1 | Read full item context | items get + epic task-get-body |
| B-2 | Read QA evidence | `db_router qa requirements-list --item YOK-N` |
| B-3 | Record QA verdict | `db_router qa run-add ...` |

#### product-manager / product-designer (no Bash)
| ID | Recipe | What it does |
|---|---|---|
| PM-1 | (no Bash needed — uses Read/Grep/Glob) | Dispatched via orchestrator's prompt context |

### C-6. Doctrine / Anti-Pattern Block (top of every packet)

Not recipes themselves, but the negative examples that drive adoption:

| ID | Anti-pattern | What it warns against |
|---|---|---|
| AP-1 | Shell-quoted function-call envelope | `printf '{"field":"X"}' \| service_client ...` — use CLI adapter or HTTP |
| AP-2 | Until-loop polling on watcher output | `until [ -s /tmp/file ]; do sleep 1; done` — trust watch_*'s lifecycle |
| AP-3 | Direct sqlite3 access | `sqlite3 <db> "..."` — use `db_router query` |
| AP-4 | Structured-field shell choreography | Read field, append in shell, write-back — use additive function call |
| AP-5 | Subagent background watcher | Bash(run_in_background) + Monitor in subagent — foreground only |
| AP-6 | cd-chain across calls | `cd .worktrees/YOK-N && cmd` — use `git -C` / `--rootdir` |
| AP-7 | Commit on main | (covered by lint-main-commit; teaching belongs in worktree recipe) |
| AP-8 | Python script in /tmp with runtime imports | (covered by lint; teaching: put scripts in `runtime/api/tools/`) |

---

## Section D — Total Recipe Count (top-down)

| Category | Count |
|---|---|
| Universal (C-1) | 12 |
| Main-session mutations (C-2) | 15 |
| Watchers (C-3) | 6 |
| Skill-bound main (C-4) | 30 (across 9 skills) |
| Subagent recipes (C-5) | 25 (across 6 subagents) |
| Anti-pattern doctrine (C-6) | 8 |
| **Total** | **96 recipes** |

**Honest assessment:** 96 is too many to ship at once. Need tiering:

- **Tier 1 (load into universal packet):** all C-1 + AP doctrine = ~20 entries
- **Tier 1 subagent-bound:** the worktree-respectful pattern (U-7) for engineer/tester = ~3 entries
- **Tier 2 (load into role-specific packet):** the skill-bound recipes for the role's primary skill (engineer→conduct, architect→shepherd, etc.) = ~5-10 per role
- **Tier 3 (referenced docs):** rare operator-only recipes (M-14, advanced path-claim) = ~10 entries

That gets the universal Tier 1 packet to ~20 entries (~30 lines each = 600 lines added). Manageable.

---

## Section E — Cross-Reference: Top-Down vs Bottom-Up

This is the synthesis. For each top-down recipe, what does telemetry say?

**Legend:**
- **✓ HIGH:** Top-down recipe IS used heavily (telemetry confirms priority)
- **○ MED:** Telemetry shows moderate use, top-down agrees
- **? LOW:** Telemetry shows rare use; top-down may be over-specifying
- **✗ MISSING:** Top-down said this is needed, telemetry shows no usage (maybe taught wrong, maybe blocked)
- **!! UNEXPECTED:** Telemetry shows heavy use, top-down didn't anticipate (something we missed in the model)

### Universal Tier (C-1)

| Top-down ID | Recipe | Bottom-up evidence | Verdict |
|---|---|---|---|
| U-1 | Resolve session_id + actor_id | 238 session_init calls; no explicit actor_id resolution pattern visible | **? LOW** — needed for HTTP dispatch but not heavily used because most adapters don't need it |
| U-2 | Read item state | 7,289 main + 80 engineer + 51 architect = 7,420+ items get calls | **✓ HIGH** |
| U-3 | Read claim state | 516 main `harness_sessions who-claims` calls | **✓ HIGH** |
| U-4 | Read recent events on ticket | 508 main `db_router events` calls | **✓ HIGH** |
| U-5 | Resolve GitHub issue from YOK-N | Not visible in bucketing — embedded in items get | **○ MED** (latent — agents resolve inline) |
| U-6 | Capture-first wrapper | 3,373 mktemp+capture calls | **✓ HIGH** (already de facto) |
| U-7 | Worktree-respectful execution | 4,203 cd+chain (engineer+tester) = ANTI-pattern showing recipe is missing | **✗ MISSING (urgent)** |
| U-8 | Git state inspect 3-line | 338+266+113 = 717 calls of the 3 components | **✓ HIGH** |
| U-9 | SQL self-orientation queries | 4,775 main `db_router query` calls | **✓ HIGH** |
| U-10 | Ouroboros log recipe | Doesn't exist yet — telemetry confirms zero usage | **✗ MISSING (intentional new recipe)** |
| U-11 | List registered function ids | 322 `command_definitions get` (similar shape) + few function-registry curls | **○ MED** |
| U-12 | HTTP function-call dispatch | 1,524 lint-shell-quoted denials = agents trying & failing | **✗ MISSING (urgent — closes 70% of denials)** |

### Main-Session Mutations (C-2)

| Top-down ID | Recipe | Bottom-up evidence | Verdict |
|---|---|---|---|
| M-1 | Cancel/stop/fail | 401 release + 426 claim + 570 items update = 800+ daily lifecycle calls | **✓ HIGH** |
| M-2 | Forward transition | Same as M-1 (same shape) | **✓ HIGH** |
| M-3 | Acquire/release claim CLI | 426 claim-work + 401 release-work-claim | **✓ HIGH** |
| M-4 | Progress Log append | Not heavily visible in telemetry — needs codification | **○ MED** (latent — done via shell choreography today) |
| M-5 | Replace structured field | 570 items update; mix of full-replace and partial via update | **✓ HIGH** |
| M-6 | Section upsert/append | 166 main `db_router sections` calls | **○ MED** |
| M-7 | Register path claim | 121 main + 9 architect + others = ~130 | **○ MED** |
| M-8 | Widen path claim | 318 main + 64 engineer + 2 architect = 384 | **✓ HIGH** |
| M-9 | Narrow path claim | 20 main + 1 each subagent = 22 | **? LOW** — Tier 3 |
| M-10 | Add item dependency | 683 main `db_router shepherd` (includes dependency-list, not just add) | **○ MED** |
| M-11 | DB-claim amend none | 166 main `sc db-claim-amend` (mostly none form) | **○ MED** |
| M-12 | DB-claim amend declared | (subset of above, rare) | **? LOW** — Tier 3 |
| M-13 | Idea-intake create | 57 main `YOKE_IDEA_INTAKE=1 db_router items add` | **○ MED** (low volume, high blast radius — must teach) |
| M-14 | Operator override | 81 main `sc claim-release` (which includes both override and normal release-where-self?) | **? LOW** — Tier 3 |
| M-15 | Rebuild board | (few standalone calls, mostly auto-triggered) | **? LOW** |

### Watchers (C-3)

| Top-down ID | Recipe | Bottom-up evidence | Verdict |
|---|---|---|---|
| W-1 | watch_pytest main bg | 206 `--print-streaming-pair` + 64 `--print-streaming-pair --rootdir` + 42 various | **✓ HIGH** |
| W-2 | watch_pytest subagent fg | 117 engineer + 71 tester foreground | **✓ HIGH** |
| W-3 | watch_doctor main bg | 268 main calls | **✓ HIGH** |
| W-4 | watch_doctor subagent fg | 44 engineer + 21 tester | **○ MED** |
| W-5 | watch_merge main bg | 318 main + 80 watch_merge --help fallbacks (gap signal) | **✓ HIGH** |
| W-6 | api_server lifecycle | 3 main calls (already running most of the time) | **? LOW** — system-level, not agent recipe |

### Skill-bound (C-4) — sample of high-attribution skills

| Top-down ID | Recipe | Bottom-up evidence | Verdict |
|---|---|---|---|
| R-2 | Refine structured-field edit | 12 lint-structured-field-transform-shell denials = misuse | **✗ MISSING** (teaching needed) |
| R-4 | idea→refining-idea transition | covered by M-2 | **✓ HIGH** |
| C-2 | Engineer dispatch from conduct | 6,259 engineer subagent calls under conduct attribution | **✓ HIGH** (orchestrator-side recipe needed) |
| C-6 | dispatch-chain-advance | 17 successful calls | **○ MED** |
| P-1 | Polish pytest re-run | 13.7k polish-attributed main calls includes plenty of test runs | **✓ HIGH** |
| U-USH-1 | watch_merge merge-worktree | 318 watch_merge calls; some in usher mode | **✓ HIGH** |
| Sh-1 | Architect dispatch | 565 architect subagent calls = main session dispatched them | **○ MED** (orchestrator recipe needed) |

### Subagent recipes (C-5)

| Top-down ID | Recipe | Bottom-up evidence | Verdict |
|---|---|---|---|
| E-1 | Engineer read epic_task body | 220 engineer `db_router epic` (mix of task-get-body and others) | **✓ HIGH** |
| E-3 | Engineer worktree-respectful pytest | 117 successful watch_pytest BUT 3,185 cd+chain = anti-pattern dominates | **✗ MISSING** (urgent) |
| E-5 | Engineer file-line check | 369 engineer wc -l calls | **✓ HIGH** |
| E-6 | Engineer progress-note-insert | Subset of 220 epic calls | **○ MED** |
| E-7 | Engineer widen path claim | 64 engineer sc path-claim-widen | **○ MED** |
| T-2 | Tester read changed files | 1,018 tester cd+chain (some are git -C in disguise) | **✗ MISSING** (urgent — same as E-3) |
| T-6 | Tester review-insert | 187 tester `db_router epic` (heavy review-* usage) | **✓ HIGH** |
| Ar-1 | Architect read plan fields | 51 architect items get + 55 db_router epic | **○ MED** |
| Ar-2 | Architect file-budget audit | 25 architect wc -l | **○ MED** |
| Ar-3 | Architect author epic task | (low standalone visibility) | **○ MED** |
| Sim-3 | Simulator cross-task trace | 339 simulator grep/rg | **✓ HIGH** |
| B-3 | Boss QA run-add | (low standalone visibility) | **? LOW** |

### Anti-patterns (C-6)

| Top-down ID | Anti-pattern | Bottom-up evidence | Verdict |
|---|---|---|---|
| AP-1 | Shell-quoted function-call | 1,524 denials | **✓ HIGH** |
| AP-2 | Until-loop polling | 236 lint-long-command-polling denials | **✓ HIGH** |
| AP-3 | sqlite3 direct | 122 lint-sqlite-cmd denials | **✓ HIGH** |
| AP-4 | Structured-field shell choreography | 12 denials (lower volume, still real) | **○ MED** |
| AP-5 | Subagent background | 255 denials | **✓ HIGH** |
| AP-6 | cd-chain across calls | 4,203 occurrences (no lint denies it — current best teaching is U-7) | **✓ HIGH** |
| AP-7 | Commit on main | 14 denials | **? LOW** |
| AP-8 | /tmp Python with runtime imports | 2 denials | **? LOW** |

---

## Section F — Things Top-Down Missed (UNEXPECTED categories)

Bottom-up patterns where the top-down model didn't predict heavy usage:

### F-1: `sed -n '1,Np' <doc>` reads — 11,913 calls in 14d

Top-down doesn't have a "read skill body" recipe because we assume the agent has the relevant skill content loaded at session start. But 11.9k `sed -n` reads of skill bodies + docs suggest agents are re-reading skill bodies mid-session, or reading docs that aren't in the packet. **Either packet is too small (we should pull more into it), or agents are doing on-demand discovery that we don't expect.**

**Action:** investigate WHICH files are most-read via `sed -n`. The top breakdown shows `.agents/skills/yoke/do/loop.md`, `do/loop-followups.md`, `do/loop-routing.md`, `do/SKILL.md`, `polish/parse-and-context`, `usher/finalize.md` are common targets. These are deep skill bodies the agent reads when chained skills don't have their full body in the prompt.

### F-2: `env-var prefixed Python invocations` — 6,424 calls

`YOKE_DB=…`, `YOKE_HOOK_AGENT_TYPE=…`, etc. The top-down model has `U-1 resolve session_id + actor_id` but didn't enumerate the broader env-var-prefixed pattern. These are mostly the harness-injected env bindings that agents pass through to subprocesses. **Probably not a recipe gap — this is harness infrastructure leakage into the tool-call surface.**

### F-3: `python3 -c inline` + `python3 - heredoc` — 1,887 + 391 = 2,278 calls

Heavy use of inline Python — agents writing Python on-the-fly. The top-down model treats this as "should be replaced by registered functions or CLI adapters." Heavy usage suggests agents are either (a) doing things the CLI adapters don't cover, or (b) using Python as a development scratchpad. **Worth a follow-up to sample the actual `python3 -c` content and see if there are missing CLI adapters.**

### F-4: 8,145 `git inspect` calls in main session

Top-down has U-8 git inspect as a 3-line sequence. But raw volume is huge — 580/day average. **Indicates agents lean heavily on git state inspection between every Yoke action.** Recipe is correct; emphasis just needs to be higher.

### F-5: 322 `command_definitions get yoke full|quick` calls

Top-down model didn't predict this. Looking at the function — it appears to load Yoke's CLI command definitions. **Probably session-init scaffolding, not a recipe the agent runs deliberately.** Investigate whether this should be auto-loaded vs reachable as a recipe.

### F-6: 306 `session_execution_scope main` calls

Top-down model didn't include this. Looks like a session-scope inspector. **Investigate — possibly an internal harness call, not an agent-facing recipe.**

---

## Section G — Things Top-Down Predicted But Bottom-Up Doesn't Confirm (CHECKING)

Top-down recipes where telemetry shows ZERO or near-zero usage. Either we over-modeled, or these are correctly used but invisible in the verb-bucketing:

### G-1: U-10 Ouroboros logging recipe

**Telemetry: 0 calls.** Doesn't exist yet — the recipe is a forward-looking proposal. Confirmed as a NEW recipe to author, not a backfill.

### G-2: M-13 Idea-intake create (with `YOKE_IDEA_INTAKE=1`)

**Telemetry: 57 calls.** Low volume — only used by `/yoke idea` skill. But it's the canonical intake; agents that DON'T use it create the orphan tickets (YOK-1791, YOK-1798 examples). **Keep in Tier 1 despite low volume — high blast radius.**

### G-3: M-15 Rebuild board

**Telemetry: low standalone.** Mostly auto-triggered by other operations. **Probably not a recipe — leave to docs.**

### G-4: PM-1 (no recipe — read-only subagent)

**Telemetry: 59 calls, mostly Read tool not Bash.** Consistent with no-Bash design. No action needed.

### G-5: Multiple skill-bound recipes (advance, polish) — telemetry shows volume but not the SHAPE

For `/yoke advance` (14k main calls) and `/yoke polish` (13.7k), the telemetry shows the volume but the verb-bucketing doesn't pinpoint specific recipes. **Need a deeper dive: for each high-attribution skill, run a sub-query showing top-10 verbs WITHIN that skill, to verify our top-down recipes match what's actually happening.**

---

## Section H — Per-Role and Skill-Bound Recipe Inventory

### TIER 2 — Skill-Bound (loaded per role/skill)

**Engineer-bound (engineer.md packet extension):**
- E-1 Read epic_task body
- E-3 Worktree-respectful pytest (foreground)
- E-5 File-line check
- E-6 Append progress note
- E-7 Widen path claim mid-implementation

**Tester-bound (tester.md):**
- T-2 Read changed files via git -C
- T-5/T-6/T-7 Review verdict sequence

**Architect-bound (architect.md):**
- Ar-2 File-budget audit
- Ar-3 Author epic task
- Ar-4 Add dependency
- Ar-5 Register planned path claim

**Simulator-bound (simulator.md):**
- Sim-3 Cross-task code trace
- Sim-4 Emit findings via section append

**Refine-bound (loaded in `/yoke refine` mode):**
- R-2 Structured-field edit
- R-3 Section upsert/append
- R-5 DB-claim amend

**Usher-bound:**
- U-USH-1 watch_merge merge-worktree
- U-USH-2 CI wait pattern

**Conduct-bound (orchestrator):**
- C-1..C-8 (engineer/tester dispatch loop + advance chain)

**Total Tier 2: ~25 entries across 7 contexts.**

### TIER 3 — On-Demand (docs, not packet)

- M-9 Path-claim narrow (22 calls)
- M-12 DB-claim amend declared
- M-14 Operator override
- M-15 Rebuild board
- B-3 Boss QA run-add (rare)
- Sh-6 shepherd_caveats authoring
- I-1 Dedup search

**Total Tier 3: ~10 entries.**

### TOTAL ACTIVE PACKET LOAD

- Universal (every agent): ~22 entries
- Per-subagent extension: 3-8 entries depending on role
- Per-skill extension for main session: 5-10 entries per active skill

For an engineer subagent dispatched in conduct: ~22 universal + ~5 engineer-bound = **~27 recipes loaded**. Manageable.

For main session in refine mode: ~22 universal + ~3 refine-bound = **~25 recipes**.

For main session in talmud (no-prior-action): ~22 universal only.

---

## Section I — Open Questions to Resolve Before Implementation

1. **U-10 (ouroboros logging) needs a new CLI adapter.** What's its exact shape? Proposed: `python3 -m yoke_core.api.service_client ouroboros-log --kind {failed,new,changed} --recipe-id ID --evidence-file PATH`. Need to author this.

2. **W-2 / W-4 subagent foreground watcher** — engineers and testers should run `watch_pytest -- runtime/api/...` foreground. The watcher wrapper SHOULD support this without `--print-streaming-pair`. Verify.

3. **U-12 HTTP function-call dispatch** — depends on `api_server start` being running. In which contexts is it running by default? Should the recipe include a `start` check? (Live-test confirmed it's already running for the main session; need to confirm for subagent contexts.)

4. **Cross-skill recipe inheritance** — if the agent is in `/yoke conduct` then nested-dispatches an engineer, does the engineer see conduct-bound recipes or just engineer-bound? Probably engineer-bound only, with no skill-bound inheritance.

5. **Section F's UNEXPECTED categories** — investigate `sed -n` skill-body reads (11.9k), `python3 -c` inline volume (1,887), `command_definitions get` (322), `session_execution_scope` (306). These may be substrate signals, not recipe gaps.

6. **Skill-bound recipes for `/yoke advance` and `/yoke polish`** — top-down enumerated some, but bottom-up shows 14k + 13.7k calls. Need a deeper per-skill verb breakdown to validate the specific recipes.

---

*Generated 2026-05-20 from first-principles agent ontology + cross-reference against the bottom-up telemetry analysis at `yoke-telemetry-frequency-table.md`.*
