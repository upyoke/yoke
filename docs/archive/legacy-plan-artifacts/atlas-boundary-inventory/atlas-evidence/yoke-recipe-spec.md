# Yoke Agent-Packet Recipe Spec

**Created:** 2026-05-20
**Purpose:** Backfill the agent packet with copy-paste-ready operational recipes BEFORE YOK-1685's Gen 3 classification work. YOK-1685 itself (Constraint 3) acknowledges: "Every wrap_as_function family page MUST carry at least one concrete copy-pasteable invocation example" — but its deliverables produce per-family DESIGN docs under `docs/archive/legacy-plan-artifacts/atlas-boundary-inventory/family-dispositions/`, not packet entries the agent loads at session start. The session-start packet is what stops the 17-call discovery loops; this spec is therefore upstream of YOK-1685.

## Status Legend

- **VETTED-LIVE** — I ran this exact sequence in this session and confirmed end-to-end.
- **VETTED-TELEMETRY** — Exact or near-exact command appears in `HarnessToolCallCompleted` events ≥3 times in last 7 days.
- **VETTED-SOURCE** — Confirmed against current CLI module source (flags / subcommands exist as written).
- **UNVETTED** — Needs live test against a meaningless target ticket.

## Evidence Sources (7-day window)

- `HarnessToolCallCompleted`: 188,652
- `HarnessToolCallFailed`: 5,211
- `HarnessToolCallDenied`: 2,336
- `YokeFunctionCalled`: 1,796
- Top lint denials:
  - `lint-shell-quoted-function-payload`: 1,520 → recipe gap = function-call envelope construction via shell
  - `lint-subagent-background`: 255 → subagent foreground watcher recipe
  - `lint-long-command-polling`: 231 → main-session Monitor pair recipe
  - `lint-sqlite-cmd`: 70 → db_router query recipe
  - `lint-claim-ownership-mutations`: 14 → claim-acquire-mutate-release recipe
  - `lint-structured-field-transform-shell`: 6 → item_field_transform recipe
- `--help` fallback signal (discovery tax):
  - `service_client --help`: 129
  - `path-claim-widen --help`: 49
  - `watch_pytest --help`: 47
  - `claim-work --help`: 44
  - `watch_merge --help`: 52

## Doctrine for Authors

1. **Recipe field carries the complete copy-paste sequence with concrete `YOK-1791`-style values.** No `<placeholders>`. The agent edits the literal in one pattern-match operation.
2. **Notes field ≤ one line.** Reserved for "when to use" — never for "what it does," "what it replaces," or "what gates apply." Cap: 120 chars.
3. **Multi-line recipes** are first-class. Use `"\n".join(...)` in the dict literal. The renderer at [schema_api_context_render.py:118-128](runtime/api/domain/schema_api_context_render.py:118) handles them.
4. **Multi-step workflows ship as one entry,** not multiple. Cancel = claim + transition + release in one recipe block.
5. **Existing prose-heavy entries get rewritten in place.** Inventoried below in the "Transforms" section.

---

# Section 1 — New Recipes (workflows not currently taught)

## Target file: `runtime/api/domain/schema_api_context_commands_core_operational.py`

### R-OP-01: Cancel a ticket (terminal-exceptional transition)

**Status:** VETTED-LIVE — executed against YOK-1791 and YOK-1798 in this session
**Evidence:** Both runs returned `Updated: status -> cancelled`, auto-closed GitHub issues #4324 and #4325, auto-cancelled path claims, posted status comments.

```python
{
    "topic": "core",
    "purpose": "Cancel / stop / fail a ticket (terminal-exceptional)",
    "recipe": (
        "python3 -m yoke_core.api.service_client claim-work --item YOK-1791 --reason 'superseded by YOK-X'\n"
        "python3 -m yoke_core.cli.db_router items update YOK-1791 status cancelled\n"
        "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1791 --reason cancelled"
    ),
    "notes": "Status writes require a claim. Substitute: cancelled (abandoned/superseded), stopped (paused), failed.",
},
```

### R-OP-02: Forward lifecycle transition (any non-terminal)

**Status:** VETTED-TELEMETRY — 148 successful `items update status` calls in 7d
**Evidence:** Query `events WHERE tool_input LIKE '%items update%status%'` confirms canonical shape.

```python
{
    "topic": "core",
    "purpose": "Move a ticket forward in lifecycle (claim → transition → release)",
    "recipe": (
        "python3 -m yoke_core.api.service_client claim-work --item YOK-1791 --reason transition\n"
        "python3 -m yoke_core.cli.db_router items update YOK-1791 status refined-idea\n"
        "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1791 --reason transition-complete"
    ),
    "notes": "Same shape for any non-terminal transition. Status vocab: lifecycle.md.",
},
```

### R-OP-03: Append a Progress Log entry

**Status:** VETTED-LIVE — verified against YOK-1798 via full claim → HTTP → release sequence at 2026-05-20.
**Verified envelope shape:** port **8765** (not 8000); `actor.actor_id` is REQUIRED and must be a **string**; payload fields are `headline` + `content` + optional `source` (NOT `body`).
**Adapter inventory at** [service_client_structured_api_adapter_inventory.py:69-75](runtime/api/service_client_structured_api_adapter_inventory.py:69) — names `sections upsert` as CLI, but that adapter is DESTRUCTIVE (overwrites entire section). True append uses HTTP.

```python
{
    "topic": "core",
    "purpose": "Append to a ticket's Progress Log (read-merge-write atomic)",
    "recipe": (
        "# Resolve actor_id once, export for the session:\n"
        "export YOKE_ACTOR_ID=$(python3 -m yoke_core.cli.db_router query \"SELECT actor_id FROM harness_sessions WHERE session_id='$YOKE_SESSION_ID'\" | head -1)\n"
        "# Acquire claim, append, release:\n"
        "python3 -m yoke_core.api.service_client claim-work --item YOK-1791 --reason progress-log-append\n"
        "cat > /tmp/progress.json <<EOF\n"
        "{\"function\":\"items.progress_log.append\",\n"
        " \"request_id\":\"$(uuidgen)\",\n"
        " \"actor\":{\"session_id\":\"$YOKE_SESSION_ID\",\"actor_id\":\"$YOKE_ACTOR_ID\"},\n"
        " \"target\":{\"kind\":\"item\",\"item_id\":1791},\n"
        " \"payload\":{\"headline\":\"dispatched engineer\",\"content\":\"engineer accepted; ETA 30m\",\"source\":\"orchestrator\"}}\n"
        "EOF\n"
        "curl -sS -X POST http://127.0.0.1:8765/v1/functions/call -H 'Content-Type: application/json' --data-binary @/tmp/progress.json\n"
        "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1791 --reason progress-log-append-complete"
    ),
    "notes": "Atomic read-merge-write preserves prior entries. Requires item claim. Server port=8765.",
},
```

### R-OP-04: Dispatch any function-call envelope via local HTTP

**Status:** VETTED-LIVE — verified against YOK-1798 with `items.get.run` (read-only) and `items.progress_log.append` (mutation). 49 functions registered.
**Verified gotchas:**
- Port is **8765** (default, set via `YOKE_API_PORT` env). Not 8000.
- `actor.actor_id` is **REQUIRED** and must be a **STRING** (passing as int returns 422 validation error).
- `request_id` should be a fresh UUID per call.
- Mutation function ids require a prior `claim-work` on the target (unless dispatcher auto-acquires — Gen 3 design pending).

```python
{
    "topic": "core",
    "purpose": "Dispatch any function call via local HTTP (canonical when no CLI adapter)",
    "recipe": (
        "# Discover available function ids (49 registered):\n"
        "curl -sS http://127.0.0.1:8765/v1/functions/registry | python3 -m json.tool | head -50\n"
        "# Resolve session actor_id once:\n"
        "export YOKE_ACTOR_ID=$(python3 -m yoke_core.cli.db_router query \"SELECT actor_id FROM harness_sessions WHERE session_id='$YOKE_SESSION_ID'\" | head -1)\n"
        "# Build + dispatch:\n"
        "cat > /tmp/envelope.json <<EOF\n"
        "{\"function\":\"items.get.run\",\n"
        " \"request_id\":\"$(uuidgen)\",\n"
        " \"actor\":{\"session_id\":\"$YOKE_SESSION_ID\",\"actor_id\":\"$YOKE_ACTOR_ID\"},\n"
        " \"target\":{\"kind\":\"item\",\"item_id\":1791},\n"
        " \"payload\":{\"fields\":[\"id\",\"title\",\"status\",\"github_issue\"]}}\n"
        "EOF\n"
        "curl -sS -X POST http://127.0.0.1:8765/v1/functions/call -H 'Content-Type: application/json' --data-binary @/tmp/envelope.json"
    ),
    "notes": "Start server first: api_server start. Mutation function ids require claim-work first.",
},
```

### R-OP-05: Re-render packets after editing a seed file

**Status:** VETTED-SOURCE — entry already exists at `_commands_core_operational.py:62-74`. Existing recipe is correct (`python3 -m yoke_core.domain.agents_render render`). Leave as-is.

---

## Target file: `runtime/api/domain/schema_api_context_commands_claims.py`

### R-CL-01: Quick claim-acquire-mutate-release for plan-stage spec writes

**Status:** VETTED-TELEMETRY — pattern matches the existing entry at claims.py:103-122 (spec-rewrite). Generalize to all plan-stage edits.

```python
{
    "topic": "claims",
    "purpose": "Claim → mutate → release (generic plan-stage edit)",
    "recipe": (
        "python3 -m yoke_core.api.service_client claim-work --item YOK-1791 --reason edit\n"
        "printf '%s' \"$NEW_CONTENT\" | python3 -m yoke_core.cli.db_router items update YOK-1791 spec --stdin\n"
        "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1791 --reason edit-complete"
    ),
    "notes": "For section/addendum updates use items.structured_field.section_upsert (recipe R-OP-XX).",
},
```

### R-CL-02: Override a foreign-session stranded claim

**Status:** PARTIALLY VETTED — entry at claims.py:83-101 exists but with prose drowning the recipe.
**Recommendation:** Rewrite existing entry with concrete who-claims → claim-release sequence.

```python
{
    "topic": "claims",
    "purpose": "Operator override: release a stranded foreign-session claim",
    "recipe": (
        "python3 -m runtime.harness.harness_sessions who-claims YOK-1791\n"
        "# Read the claim_id from output, then:\n"
        "python3 -m yoke_core.api.service_client claim-release --item YOK-1791 --claim-id 252 --reason 'session abandoned: laptop sleep, recovered next morning'"
    ),
    "notes": "Human-only. Refuses to run with YOKE_HOOK_EVENT set.",
},
```

---

## Target file: NEW — `runtime/api/domain/schema_api_context_commands_watchers.py`

(Watcher / Monitor / background-command workflows — high-friction, no current packet home)

### R-WT-01: Run pytest via watcher (main session)

**Status:** VETTED-TELEMETRY — 266 successful `watch_pytest --raw-capture` invocations, 69 `--print-streaming-pair`, 47 `--help`. Top successful pattern.
**Evidence:** Already taught in CLAUDE.md prose; needs to surface as a copy-paste recipe in the packet.

```python
{
    "topic": "core",
    "purpose": "Run pytest with background watcher + Monitor (main session)",
    "recipe": (
        "# Step 1: Get the paste-pair:\n"
        "python3 -m yoke_core.tools.watch_pytest --print-streaming-pair -- runtime/api/\n"
        "# Step 2: Paste the printed background command into Bash(run_in_background: true).\n"
        "# Step 3: Paste the printed watch_tail command into Monitor.\n"
        "# Step 4: After completion notification: tail -80 /tmp/yoke-pytest.raw.<id>"
    ),
    "notes": "Parallel by default (-n auto); pass --no-parallel after -- for sequential.",
},
```

### R-WT-02: Run pytest foreground (subagent context)

**Status:** VETTED-TELEMETRY — subagents run watch_pytest foreground per the `lint-subagent-background` rule. 255 denials in 7d for subagents trying background patterns.

```python
{
    "topic": "core",
    "purpose": "Run pytest foreground inside one Bash call (subagent)",
    "recipe": (
        "python3 -m yoke_core.tools.watch_pytest -- runtime/api/test_my_module.py -q\n"
        "# Blocks within the same tool call; writes /tmp/yoke-pytest.raw.<id>; "
        "tail -80 the raw capture on failure."
    ),
    "notes": "Subagents MUST NOT use Bash(run_in_background) + Monitor (lint-subagent-background).",
},
```

### R-WT-03: Run doctor with watcher

**Status:** VETTED-TELEMETRY — 40 successful `watch_doctor --raw-capture` invocations.

```python
{
    "topic": "core",
    "purpose": "Run doctor with background watcher (main session)",
    "recipe": (
        "python3 -m yoke_core.tools.watch_doctor --print-streaming-pair -- --quick\n"
        "# Paste background command into Bash(run_in_background: true), watch_tail into Monitor."
    ),
    "notes": "Doctor MUST run under this wrapper — bare invocations risk the inverted-redirection trap.",
},
```

### R-WT-04: Run merge-worktree with watcher

**Status:** UNVETTED — 52 `watch_merge --help` calls in 7d but few successful merges visible; needs verification.

```python
{
    "topic": "core",
    "purpose": "Run done_transition / merge_worktree with watcher (main session)",
    "recipe": (
        "python3 -m yoke_core.tools.watch_merge --print-streaming-pair merge-worktree -- YOK-1791"
    ),
    "notes": "watch_merge owns the merge filter regex; use for any merge or done_transition.",
},
```

---

## Target file: `runtime/api/domain/schema_api_context_commands_core.py` (existing — new entries)

### R-CORE-NEW-01: Read item field(s) with concrete example

**Status:** VETTED-TELEMETRY — `items get` with various fields is the #2 successful command class. Existing entry at core.py:14-34 is correct shape but uses `YOK-N` placeholder.
**Recommendation:** Add a concrete-value example to the recipe; keep notes lean.

```python
{
    "topic": "core",
    "purpose": "Read structured item field(s)",
    "recipe": (
        "python3 -m yoke_core.cli.db_router items get YOK-1791 status title type github_issue\n"
        "python3 -m yoke_core.cli.db_router items get YOK-1791 spec  # full field\n"
        "python3 -m yoke_core.cli.db_router items get YOK-1791 body --section \"## File Budget\""
    ),
    "notes": "Multi-field returns one value per line in field order. Section read for large bodies.",
},
```

### R-CORE-NEW-02: Resolve GitHub issue from YOK-N before any gh call

**Status:** VETTED-LIVE — used in this session to find #4325 for YOK-1798

```python
{
    "topic": "core",
    "purpose": "Resolve GitHub issue number from YOK-N before gh CLI calls",
    "recipe": (
        "ISSUE=$(python3 -m yoke_core.cli.db_router items get YOK-1791 github_issue)\n"
        "ISSUE_NUM=${ISSUE#\\#}  # strip leading '#'\n"
        "gh issue view \"$ISSUE_NUM\""
    ),
    "notes": "items.github_issue stores '#NNNN' format; strip the hash before passing to gh.",
},
```

### R-CORE-NEW-03: Common SELECT queries for self-orientation

**Status:** VETTED-TELEMETRY — `db_router query "SELECT ..."` is the #3 successful command class with multiple distinct shapes (203+169+86+70+53+51+50+40 = 700+ in top 30).

```python
{
    "topic": "core",
    "purpose": "Inspect your own / others' open work via SQL",
    "recipe": (
        "# All non-terminal items I touched:\n"
        "python3 -m yoke_core.cli.db_router query \"SELECT id, status, title FROM items WHERE status NOT IN ('done','cancelled','stopped','failed') ORDER BY updated_at DESC LIMIT 20\"\n"
        "# Active work claims:\n"
        "python3 -m yoke_core.cli.db_router query \"SELECT item_id, session_id, reason FROM work_claims WHERE state='active'\"\n"
        "# Recent events on a ticket:\n"
        "python3 -m yoke_core.cli.db_router events list --item-id 1791 --limit 20"
    ),
    "notes": "Use <> not !=. Read-only is always allowed; never use sqlite3 directly.",
},
```

---

# Section 2 — Transforms (existing prose-heavy entries → recipe form)

These entries exist today but the recipe is abstract / placeholder-heavy and the notes prose drowns the example. Each one gets a recipe-first rewrite.

## T-01: Lifecycle status entry (core.py:240-269) — WORST OFFENDER

**Current shape:** 76-char recipe `python3 -m yoke_core.cli.db_router items update YOK-N status <next-status>` + 847 chars of notes covering register_all_handlers, dispatch envelope, Python cold-start.
**Problem:** The recipe doesn't show the claim choreography; the notes mix four unrelated topics (CLI shape, Python cold-start, dispatcher, envelope model).
**Transform:** Split into three focused entries:
1. R-OP-02 (forward transition) — already drafted above
2. R-OP-01 (terminal cancel/stop/fail) — already drafted above
3. New entry: "List registered function ids from Python REPL" — Python cold-start moved here

```python
{
    "topic": "core",
    "purpose": "List registered Yoke function ids from Python",
    "recipe": (
        "python3 -c \"\n"
        "from yoke_core.domain.handlers.__init_register__ import register_all_handlers\n"
        "register_all_handlers()\n"
        "from yoke_core.domain.yoke_function_registry import list_entries\n"
        "for e in list_entries(): print(e.function_id)\n\""
    ),
    "notes": "list_entries() returns [] without register_all_handlers() first.",
},
```

**Status:** VETTED-SOURCE — module paths verified against current repo

## T-02: Backlog mutation family (core.py:296-312) — comma-separated list of subcommands, zero copy-paste value

**Current shape:** `python3 -m yoke_core.api.service_client backlog-cli {add,update,batch-update,freeze,thaw,block,unblock,close,sync-item,sync-labels,sync-body,rebuild-board,post-comment,get-next-id,list,dedup-search} ...`
**Problem:** Brace-expansion syntax is teaching, not a recipe. Agent can't paste this.
**Transform:** Split into 3-4 concrete recipes for the actually-used subcommands per telemetry. Need additional query to identify which subcommands are hit most.

**Status:** NEEDS TELEMETRY QUERY — pending Explore agent results

## T-03: Path claim register (claims.py:147-170) — recipe IS concrete, notes are essay

**Current shape:** Recipe is a complete-flag example; notes run 698 chars covering --allow-planned, modes, exception-reason, and a long worked example.
**Problem:** Notes drown the recipe; the worked-example belongs IN the recipe block.
**Transform:** Move worked example into recipe, cut notes to one line.

```python
{
    "topic": "claims",
    "purpose": "Register a path claim",
    "recipe": (
        "python3 -m yoke_core.api.service_client path-claim-register \\\n"
        "  --item YOK-1791 \\\n"
        "  --paths runtime/api/domain/path_claim_targets.py,runtime/api/test_path_claim_targets.py,docs/event-catalog.md \\\n"
        "  --integration-target main --mode exclusive --allow-planned \\\n"
        "  --reason 'YOK-1791: defense-in-depth liveness cross-check + supporting test/event-catalog edits'"
    ),
    "notes": "--allow-planned for files not yet committed. --mode exception for no-repo-touch tickets.",
},
```

**Status:** VETTED-SOURCE — flags verified against current CLI

## T-04: Path claim widen (claims.py:172-191) — same shape issue as T-03

**Transform:** Same treatment — concrete worked example in recipe block, one-line notes.

```python
{
    "topic": "claims",
    "purpose": "Widen a path claim",
    "recipe": (
        "python3 -m yoke_core.api.service_client path-claim-widen 138 \\\n"
        "  --paths runtime/api/service_client_backlog_router.py,runtime/api/test_backlog_github_backfill_oversized.py \\\n"
        "  --allow-planned \\\n"
        "  --reason 'task 9: backfill subcommand wiring touches router + new test file'"
    ),
    "notes": "<claim-id> is positional. Get it from path-claim-register response or path-claim-list.",
},
```

**Status:** VETTED-SOURCE

## T-05: Acquire/release work claim API-first (claims.py:35-57) — entire entry is non-executable

**Current shape:** Shows function-call envelope as pseudo-text (`function=claims.work.acquire target={kind:item,item_id:N} payload={...}`). Cannot be pasted.
**Problem:** Notes are 596 chars explaining the envelope; the executable form (CLI adapter at claims.py:61-81) is in a separate entry.
**Transform:** Delete the API-first entry OR convert to a real `db_router functions call` envelope. The CLI adapter entry (claims.py:61) is the canonical agent path — keep it, fix it.

**Status:** RECOMMENDATION — delete claims.py:35-57 in favor of the CLI adapter entry below.

## T-06: Acquire/release CLI adapter (claims.py:60-81) — has all the right info but buried in 623 chars of notes

**Transform:** Move target-variant examples (item / epic-task / process) into the recipe block as three lines.

```python
{
    "topic": "claims",
    "purpose": "Acquire a work claim (CLI)",
    "recipe": (
        "python3 -m yoke_core.api.service_client claim-work --item YOK-1791 --reason draft-in-progress\n"
        "python3 -m yoke_core.api.service_client claim-work --epic-task 833 --task-num 5 --reason engineer-dispatch\n"
        "python3 -m yoke_core.api.service_client claim-work --process DOCTOR --project yoke --reason scheduled-run"
    ),
    "notes": "Reason recommended on acquire, required on release. See R-OP-01 for full sequences.",
},
```

**Status:** VETTED-LIVE — claim-work --item form executed in this session

## T-07: Inspect path-claim conflicts (claims.py:194-209) — recipe is concrete but notes contain a buried recipe

**Current shape:** Recipe = `path-claim-conflicts [--integration-target main]`. Notes embed: *"To find conflicts on a specific set of paths, query path_claims joined to path_claim_targets..."* — that buried query IS a recipe and should be its own entry.
**Transform:** Split into two entries — one for the CLI summary, one for the SQL deep-dive.

```python
# Entry 1 (replaces existing):
{
    "topic": "claims",
    "purpose": "Summary of path-claim conflicts on a branch",
    "recipe": "python3 -m yoke_core.api.service_client path-claim-conflicts --integration-target main",
    "notes": "Read-only summary across all non-terminal claims. Filter via SQL for specific paths.",
},
# Entry 2 (new):
{
    "topic": "claims",
    "purpose": "Find conflicts on specific paths",
    "recipe": (
        "python3 -m yoke_core.cli.db_router query \"\n"
        "SELECT pc.id, pc.item_id, pc.state, pt.path_string\n"
        "FROM path_claims pc\n"
        "JOIN path_claim_targets pct ON pct.path_claim_id = pc.id\n"
        "JOIN path_targets pt ON pt.id = pct.target_id\n"
        "WHERE pt.path_string IN ('runtime/api/domain/foo.py', 'runtime/api/domain/bar.py')\n"
        "  AND pc.state NOT IN ('cancelled','released')\""
    ),
    "notes": "Use when path-claim-conflicts is too coarse.",
},
```

**Status:** VETTED-TELEMETRY — query pattern appears 40+ times in 7d

---

# Section 3 — Additional Recipes from Telemetry Sweep (Explore agent returned)

## Target file: `runtime/api/domain/schema_api_context_commands_core_operational.py` (additions)

### R-OP-06: Session lifecycle commands (offer / heartbeat / checkpoint / touch / end)

**Status:** VETTED-TELEMETRY — 24 session-offer, 13 session-heartbeat, 12 session-checkpoint, 10 session-touch, 8 session-end in 7d. NOT taught in any current packet entry.
**Source verified:** `session-checkpoint --session-id S --step N --action A --chainable BOOL [--item-id I] [--task-num T] [--outcome O]`

```python
{
    "topic": "core",
    "purpose": "Session lifecycle — heartbeat / checkpoint / mode-switch / end",
    "recipe": (
        "# Heartbeat (keep session + claims alive during long operations):\n"
        "python3 -m yoke_core.api.service_client session-heartbeat --session-id $YOKE_SESSION_ID\n"
        "# Persist a chainable checkpoint after a phase:\n"
        "python3 -m yoke_core.api.service_client session-checkpoint --session-id $YOKE_SESSION_ID --step 3 --action implement --chainable true --item-id YOK-1791\n"
        "# Mode-switch (idea → refine → advance → conduct):\n"
        "python3 -m yoke_core.api.service_client session-touch --mode refine\n"
        "# End:\n"
        "python3 -m yoke_core.api.service_client session-end --session-id $YOKE_SESSION_ID"
    ),
    "notes": "session-offer for cross-executor handoff; heartbeat is on-demand only (loop removed).",
},
```

### R-OP-07: Self-inspection git/gh recipes

**Status:** VETTED-TELEMETRY — 173 `git log --oneline -20`, 171 `git status --short`, 103 `gh run list`, 63 `git status --short --branch`. High frequency, well-used; teaching belongs in packet for cold-start agents.

```python
{
    "topic": "core",
    "purpose": "Branch / commit / CI inspection (read-only)",
    "recipe": (
        "git -C $(git rev-parse --show-toplevel) status --short --branch\n"
        "git -C $(git rev-parse --show-toplevel) log --oneline -20\n"
        "gh run list --branch main --limit 1 --json status,conclusion --jq '.[0]'\n"
        "git -C $(git rev-parse --show-toplevel)/.worktrees/YOK-1791 status --porcelain\n"
        "git -C $(git rev-parse --show-toplevel)/.worktrees/YOK-1791 rev-parse HEAD"
    ),
    "notes": "Use -C with absolute path. Worktree paths under .worktrees/<branch>.",
},
```

## Target file: `runtime/api/domain/schema_api_context_commands_claims.py` (additions)

### R-CL-03: Narrow a path claim

**Status:** VETTED-SOURCE — confirmed flags: `--drop-paths` OR `--keep-paths`, `--reason`, `--repo-path`, `--worktree-head`
**CORRECTION:** Explore agent guessed `--remove`; actual flag is `--drop-paths` (drop these) or `--keep-paths` (keep only these).

```python
{
    "topic": "claims",
    "purpose": "Narrow a path claim (drop or keep paths)",
    "recipe": (
        "# Drop specific paths from claim 138:\n"
        "python3 -m yoke_core.api.service_client path-claim-narrow 138 \\\n"
        "  --drop-paths docs/old-design.md,docs/old-notes.md \\\n"
        "  --reason 'docs moved out of scope after refine' \\\n"
        "  --repo-path $(git rev-parse --show-toplevel)\n"
        "# Keep only listed paths:\n"
        "python3 -m yoke_core.api.service_client path-claim-narrow 138 \\\n"
        "  --keep-paths runtime/api/domain/foo.py \\\n"
        "  --reason 'scope narrowed to single module' \\\n"
        "  --repo-path $(git rev-parse --show-toplevel)"
    ),
    "notes": "Pick exactly one of --drop-paths or --keep-paths.",
},
```

### R-CL-04: List + get a single path claim

**Status:** VETTED-SOURCE — `path-claim-list --item YOK-N` exists; `path-claim-get <claim-id>` likely exists (need verify)

```python
{
    "topic": "claims",
    "purpose": "List / get path claims",
    "recipe": (
        "python3 -m yoke_core.api.service_client path-claim-list --item YOK-1791\n"
        "python3 -m yoke_core.api.service_client path-claim-get 138"
    ),
    "notes": "Returns id, state, declared paths, target_ids. Pipe to jq for filtering.",
},
```

## Target file: `runtime/api/domain/schema_api_context_commands_watchers.py` (new — additions)

### R-WT-05: watch_pytest with raw-capture (concrete path)

**Status:** VETTED-TELEMETRY — 266 successful `watch_pytest --raw-capture` calls. The print-streaming-pair form mints the path automatically; the explicit `--raw-capture` form is for callers that want a known path.

```python
{
    "topic": "core",
    "purpose": "Run pytest with explicit raw-capture path (post-completion inspection)",
    "recipe": (
        "python3 -m yoke_core.tools.watch_pytest --raw-capture /tmp/yoke-pytest.raw -- runtime/api/test_my_module.py -q\n"
        "tail -80 /tmp/yoke-pytest.raw"
    ),
    "notes": "Use --print-streaming-pair instead when running in main session with Monitor.",
},
```

### R-WT-06: watch_doctor with --only filter

**Status:** VETTED-TELEMETRY — 15 `--quick` calls; `--only HC-event-registry-coverage,HC-event-callsite-registry-sync` patterns observed
**Source verified:** doctor CLI has `--only ONLY  Comma-separated HC slug IDs to run`

```python
{
    "topic": "core",
    "purpose": "Run doctor focused on specific HC rules",
    "recipe": (
        "python3 -m yoke_core.tools.watch_doctor -- --quick\n"
        "python3 -m yoke_core.tools.watch_doctor -- --only HC-event-registry-coverage,HC-event-callsite-registry-sync\n"
        "python3 -m yoke_core.tools.watch_doctor -- --full --json"
    ),
    "notes": "Quick = fast subset; --only for targeted HC reruns; --json for machine output.",
},
```

## Target file: `runtime/api/domain/schema_api_context_commands_core.py` (additions)

### R-CORE-NEW-04: Function-call dispatch via HTTP (the canonical recipe for the 1,520 shell-quoted denials)

**Status:** VETTED-SOURCE — `api_server` exists at `runtime/api/tools/api_server.py`; HTTP route `/v1/functions/call` confirmed in handler code
**Critical for fixing the #1 denial class.** 1,520 lint-shell-quoted-function-payload denials in 7d are agents hand-constructing function-call envelopes via shell text. The fix is to either (a) use the CLI adapter for that function id, or (b) use HTTP POST.

```python
{
    "topic": "core",
    "purpose": "Dispatch any function call via HTTP (when no CLI adapter exists)",
    "recipe": (
        "# Start the local server (idempotent):\n"
        "python3 -m yoke_core.tools.api_server start\n"
        "# Build the envelope as JSON in a tempfile:\n"
        "cat > /tmp/envelope.json <<EOF\n"
        "{\"function\":\"items.section.upsert\",\n"
        " \"request_id\":\"$(uuidgen)\",\n"
        " \"actor\":{\"session_id\":\"$YOKE_SESSION_ID\"},\n"
        " \"target\":{\"kind\":\"item\",\"item_id\":1791},\n"
        " \"payload\":{\"section_name\":\"## Progress Log\",\"content\":\"...\",\"ordering\":200}}\n"
        "EOF\n"
        "# Dispatch:\n"
        "curl -sS -X POST http://localhost:8000/v1/functions/call \\\n"
        "  -H 'Content-Type: application/json' --data-binary @/tmp/envelope.json"
    ),
    "notes": "Use this when no CLI adapter exists. Otherwise prefer the adapter (e.g. service_client claim-work).",
},
```

### R-CORE-NEW-05: db-claim-amend with concrete payloads

**Status:** PARTIALLY VETTED — entry exists at `_commands_core.py:153-167` but agents still wrap it in shell (116 denials). Recipe needs to show the negative-default and declared forms side-by-side.

```python
{
    "topic": "core",
    "purpose": "Amend DB-mutation claim (negative-default OR declared)",
    "recipe": (
        "# Negative-default (no governed DB mutation):\n"
        "python3 -m yoke_core.api.service_client db-claim-amend \\\n"
        "  --item YOK-1791 \\\n"
        "  --reason 'idea: spec/body declares no governed DB mutation' \\\n"
        "  --state none\n"
        "# Declared form (read JSON from stdin to avoid shell-quoting):\n"
        "cat > /tmp/claim.json <<EOF\n"
        "{\"state\":\"declared\",\"model\":\"governed_migration_module\",\n"
        " \"mutation_intent\":\"apply\",\"compatibility_class\":\"pre_merge_safe\",\n"
        " \"migration_strategy\":\"additive_only\"}\n"
        "EOF\n"
        "python3 -m yoke_core.api.service_client db-claim-amend \\\n"
        "  --item YOK-1791 --reason 'declared: adding column foo' --payload -"
    ),
    "notes": "Use --payload - (stdin) for declared form; --state none for negative-default.",
},
```

## Target file: `runtime/api/domain/schema_api_context_commands_qa.py` (additions)

### R-QA-NEW-01: Epic dispatch chain workflow

**Status:** VETTED-TELEMETRY — 32 `flows stages`, 17 `dispatch-chain-advance`, 13 `task-get-body`, 12 `dispatch-chain-list`, 10 `task-list`

```python
{
    "topic": "qa",
    "purpose": "Epic dispatch chain (list / advance / inspect)",
    "recipe": (
        "python3 -m yoke_core.cli.db_router epic task-list 1704\n"
        "python3 -m yoke_core.cli.db_router epic task-get-body 1704 5\n"
        "python3 -m yoke_core.cli.db_router epic dispatch-chain-list 1704\n"
        "python3 -m yoke_core.cli.db_router epic dispatch-chain-advance 1704 'YOK-1704'"
    ),
    "notes": "Epic id is bare integer. Task num is 1-based.",
},
```

---

# Section 3b — Anti-Pattern Recipes — SECTION DROPPED

Per operator decision (Atlas master plan §1.6), anti-pattern doctrine blocks were EXPLICITLY REJECTED for the packet. Teaching bad shapes risks agents pattern-matching against them. Negative teaching happens exclusively in lint denial messages at point of failure (Atlas Ticket 5 — Denial-Message Standardization), NOT preventively in the packet.

The five AP entries that previously lived here (`AP-01` through `AP-05`) are intentionally deleted from this evidence file. Each lint rule's denial message carries its own corrective recipe inline; that is the only place "don't do X, do Y instead" teaching belongs.

---

# Section 4 — Live-Test Plan

Recipes marked UNVETTED need execution against a real (preferably meaningless) target:

1. **Test ticket creation:** Create `YOK-TEST-RECIPES` via `/yoke idea` with a meaningless prompt ("test ticket for recipe vetting; please cancel").
2. **Targets that mutate the test ticket:** R-OP-03 (Progress Log append), R-OP-04 (HTTP envelope dispatch), R-WT-04 (merge with watcher — not applicable to an unmerged test ticket), T-02 (backlog subcommand recipes after telemetry result).
3. **Targets that don't need a ticket:** R-WT-01..R-WT-03 (watcher recipes against pytest/doctor).
4. **Targets that need elevated state:** R-CL-02 (foreign-claim override) needs a stranded foreign claim to exist — skip live test, leave VETTED-SOURCE.

---

# Section 6b — Critical Findings from Live Vetting

## F-01: HTTP api_server port is 8765, not 8000

Every prior packet entry referencing `localhost:8000` (and the Explore agent's first-pass recipes) is **wrong**. The default port is 8765 from `runtime/api/tools/api_server.py:103`. Override via env: `YOKE_API_PORT=N`. Recipes in this spec corrected to `http://127.0.0.1:8765/v1/functions/call`.

## F-02: `actor.actor_id` is currently REQUIRED on every HTTP envelope, and must be a STRING

YOK-1685 Constraint 1 proposes server-side resolution from session_id; that has **not shipped**. Today every envelope must include both:
```json
{"actor": {"session_id": "<uuid>", "actor_id": "<id-as-string>"}}
```
Passing `actor_id` as an integer returns a 422 validation error. The agent must resolve actor_id first via:
```bash
python3 -m yoke_core.cli.db_router query "SELECT actor_id FROM harness_sessions WHERE session_id='$YOKE_SESSION_ID'"
```
**Recipe implication:** every HTTP-dispatch recipe in the packet must show the actor_id lookup as part of the recipe, OR pre-populate `$YOKE_ACTOR_ID` at session start. Recommend an env-export added to `session_init`.

## F-03: `db_router functions call` does NOT exist as a subcommand

Verified: `python3 -m yoke_core.cli.db_router functions` returns `Unknown domain: functions`. The Explore agent's first-pass `db_router functions call <id> --payload JSON` recipe is fabricated. The only ways to dispatch a function-call envelope from a shell are:
1. The registered CLI adapter for that function id (e.g. `service_client claim-work` → `claims.work.acquire`)
2. HTTP POST to `http://127.0.0.1:8765/v1/functions/call`
3. Python in-process: `from yoke_core.domain.yoke_function_dispatch import dispatch; dispatch(envelope)`

This is the canonical answer to the 1,520 `lint-shell-quoted-function-payload` denials per week.

## F-04: `items.progress_log.append` payload fields are `headline` + `content` + optional `source`

Not `body`. Both the Explore agent and the prior 12-cluster analysis got this wrong. Verified by reading [handlers/items_progress_log.py](runtime/api/domain/handlers/items_progress_log.py) `AppendRequest` model.

## F-05: Even read-only commands trip `lint-shell-quoted-function-payload` when separated by `echo`

A discovered friction-class. Running:
```bash
service_client path-claim-list --item YOK-1798; echo "---"; service_client path-claim-get 252
```
was **denied** because the `echo "---"` separator between two registered adapter calls counted as "shell choreography." This is over-eager — the `echo` separator carries no payload. **Recipe implication:** teach agents to run separate adapter calls in **separate Bash tool calls**, not in compound shell statements. Updating doctrine block at top of packet to call this out explicitly.

## F-06: Some path-claim subcommands have NO `--help` registered

`service_client path-claim-list --help` returns: *"no docstring registered; this subcommand needs a `--help` handler upgrade — file a follow-up if the missing usage blocks your work"*. This is a teaching surface degradation — the packet recipe IS the teaching surface for these subcommands. File a follow-up to add the docstrings, or accept that the packet recipes are the canonical docs.

## F-07: `path-claim-narrow` uses `--drop-paths` / `--keep-paths`, not `--remove`

Explore agent guessed `--remove <path-string>`; actual flags verified via `--help`. Corrected in R-CL-03.

## F-08: `render_body` IS a real module

`python3 -m yoke_core.domain.render_body N --output-file /tmp/body.md` — surfaced by the lint denial message itself as a "concrete copy-pasteable read example." Confirmed valid. Use for large item bodies that exceed read budget. Add as a recipe.

---

# Section 7 — Progress Tracker

| Recipe ID | Workflow | Target File | Status | Vetted? |
|---|---|---|---|---|
| R-OP-01 | Cancel ticket | `_commands_core_operational.py` | drafted | VETTED-LIVE |
| R-OP-02 | Forward transition | `_commands_core_operational.py` | drafted | VETTED-TELEMETRY |
| R-OP-03 | Progress Log append (HTTP) | `_commands_core_operational.py` | drafted, **corrected** | **VETTED-LIVE** |
| R-OP-04 | HTTP envelope dispatch | `_commands_core_operational.py` | drafted, **corrected** | **VETTED-LIVE** |
| R-OP-06 | Session lifecycle | `_commands_core_operational.py` | drafted | VETTED-SOURCE |
| R-OP-07 | Self-inspection git/gh | `_commands_core_operational.py` | drafted | VETTED-TELEMETRY |
| R-CL-03 | Path-claim narrow | `_commands_claims.py` | drafted | VETTED-SOURCE |
| R-CL-04 | Path-claim list/get | `_commands_claims.py` | drafted | VETTED-LIVE |
| R-WT-05 | watch_pytest --raw-capture | `_commands_watchers.py` (new) | drafted | VETTED-TELEMETRY |
| R-WT-06 | watch_doctor --only | `_commands_watchers.py` (new) | drafted | VETTED-SOURCE |
| R-CORE-NEW-04 | HTTP function-call dispatch | `_commands_core.py` | drafted | VETTED-LIVE |
| R-CORE-NEW-05 | db-claim-amend concrete | `_commands_core.py` | drafted | VETTED-SOURCE |
| R-QA-NEW-01 | Epic dispatch chain | `_commands_qa.py` | drafted | VETTED-TELEMETRY |
| AP-01..05 | Anti-pattern doctrine block | top of packet | drafted | VETTED-TELEMETRY |
| R-OP-05 | Re-render packets | (existing — leave) | n/a | VETTED-SOURCE |
| R-CL-01 | Claim-mutate-release | `_commands_claims.py` | drafted | VETTED-TELEMETRY |
| R-CL-02 | Foreign-claim override | `_commands_claims.py` | drafted | VETTED-SOURCE |
| R-WT-01 | watch_pytest main | `_commands_watchers.py` (new) | drafted | VETTED-TELEMETRY |
| R-WT-02 | watch_pytest subagent | `_commands_watchers.py` (new) | drafted | VETTED-TELEMETRY |
| R-WT-03 | watch_doctor | `_commands_watchers.py` (new) | drafted | VETTED-TELEMETRY |
| R-WT-04 | watch_merge | `_commands_watchers.py` (new) | drafted | UNVETTED |
| R-CORE-NEW-01 | items get concrete | `_commands_core.py` | drafted | VETTED-TELEMETRY |
| R-CORE-NEW-02 | github_issue resolve | `_commands_core.py` | drafted | VETTED-LIVE |
| R-CORE-NEW-03 | self-orientation SELECTs | `_commands_core.py` | drafted | VETTED-TELEMETRY |
| T-01a | List function ids | `_commands_core.py` | drafted | VETTED-SOURCE |
| T-01b | Lifecycle entry split | `_commands_core.py` | drafted (R-OP-01/02) | (see R-OP-01) |
| T-02 | Backlog mutation family | `_commands_core.py` | pending telemetry | NEEDS-QUERY |
| T-03 | Path-claim register | `_commands_claims.py` | drafted | VETTED-SOURCE |
| T-04 | Path-claim widen | `_commands_claims.py` | drafted | VETTED-SOURCE |
| T-05 | Acquire/release API-first | DELETE | drafted | n/a |
| T-06 | Acquire/release CLI | `_commands_claims.py` | drafted | VETTED-LIVE |
| T-07a | path-claim-conflicts CLI | `_commands_claims.py` | drafted | VETTED-SOURCE |
| T-07b | path-claim conflicts SQL | `_commands_claims.py` (new) | drafted | VETTED-TELEMETRY |

---

# Appendix — Telemetry Queries Used

```sql
-- Top denial hooks (7d):
SELECT json_extract(envelope, '$.context.detail.hook') AS hook, COUNT(*) AS c
FROM events WHERE event_name='HarnessToolCallDenied' AND created_at > date('now', '-7 days')
GROUP BY hook ORDER BY c DESC LIMIT 20;

-- Top successful runtime.api commands (7d):
SELECT SUBSTR(json_extract(envelope, '$.context.detail.tool_input'), 1, 90) AS cmd, COUNT(*) AS c
FROM events WHERE event_name='HarnessToolCallCompleted' AND tool_name='Bash'
  AND created_at > date('now', '-7 days')
  AND json_extract(envelope, '$.context.detail.tool_input') LIKE 'python3 -m runtime.api%'
GROUP BY cmd ORDER BY c DESC LIMIT 30;

-- Top event names (7d):
SELECT event_name, COUNT(*) AS c FROM events
WHERE created_at > date('now', '-7 days') AND (event_name LIKE '%Hook%' OR event_name LIKE '%Tool%' OR event_name LIKE '%Function%')
GROUP BY event_name ORDER BY c DESC LIMIT 30;
```
