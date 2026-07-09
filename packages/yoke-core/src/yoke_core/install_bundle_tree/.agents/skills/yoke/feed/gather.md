# Gather

Collect all context needed for feed's decision phase. This phase is read-only -- it queries state but mutates nothing.

## 1.1 Resolve Scope

Determine whether feed is running against:

- the full non-terminal, non-frozen frontier (`_scope_ids` is empty), or
- an explicit scoped subset of items (`_scope_ids` provided by the operator).

When scoped:
- deep-read and report primarily on the listed items
- still inspect the surrounding frontier and dependency graph enough to encode truthful blockers and merge order
- do not silently expand the mutation scope beyond the listed items unless a shared-surface blocker forces it

## 1.2 Read SML Docs

Read all four Strategic Markdown Layer docs from the DB authority:

```bash
yoke strategy doc get MISSION
yoke strategy doc get LANDSCAPE
yoke strategy doc get VISION
yoke strategy doc get MASTER-PLAN
```

Skip this section entirely when `_no_new_tickets` is true and the run is truly graph-refresh-only. Otherwise retain the full content of each doc in context. Pay special attention to:
- **MASTER-PLAN.md** generation/wave structure -- identifies what is next to materialize
- **VISION.md** near-term priorities and capability targets
- **LANDSCAPE.md** competitive and technical constraints that affect sequencing
- **MISSION.md** invariant strategic anchors

## 1.3 Query Target And Frontier Items

Get all non-terminal items (everything except `done`, `cancelled`, `stopped`, `failed`):

```bash
yoke items list --project "$_project" --fields "id,title,status,type,priority"
```

The status filter accepts one value per call, so list the project's items
and keep only rows whose `status` is non-terminal (drop `done`,
`cancelled`, `stopped`, `failed`). This produces the full frontier item
list. Record every item's `id`, `title`, `status`, `type`, and `priority`.

Derive `_target_items`:
- if `_scope_ids` is non-empty, filter the frontier list to those IDs and fail clearly if any requested item is missing
- otherwise, `_target_items` is the full frontier list

## 1.4 Deep Read Structured Item Context

For every item in `_target_items`, read the DB-backed content that feed may need to update after recent landings:

```bash
# For each target item:
yoke items get YOK-{id} body
yoke items get YOK-{id} spec
yoke items get YOK-{id} design_spec
yoke items get YOK-{id} technical_plan
yoke items get YOK-{id} worktree_plan
yoke items get YOK-{id} shepherd_caveats
```

Also note:
- which structured fields are empty
- which items are pre-ready vs execution-ready
- which acceptance criteria or assumptions mention files, schemas, prompts, hooks, tests, docs, or deployment surfaces that may have changed

Summarize findings:
- how many items are in each status bucket
- which target items lack enough definition to execute safely
- which items appear to overlap or conflict in scope

## 1.5 Read Existing Dependencies

For each target item, query its dependency edges:

```bash
# For each target item:
yoke shepherd dependency-list YOK-{id}
```

Build a mental model of the current dependency graph:
- Which items block which other items
- What gate types are in use (activation, integration, closure)
- Which edges are `source='feed'` (generated) vs `source='operator'`/`source='idea'` (manual)
- Any edges where the blocker item is in a terminal status (`done`, `cancelled`) -- these are candidates for staleness

## 1.6 Read Recent Commits And Landed Diff Stats

Get recent codebase changes for context on what has landed:

```bash
git log --oneline -30
git log --oneline --since="3 days ago"
```

For the commits or landed SUN items most likely to affect `_target_items`, inspect what actually changed:

```bash
git diff <commit>~1..<commit> --stat
```

For each recently landed change, record:
- the landed item/commit identity
- changed files, schemas, contracts, prompts, hooks, docs, tests, and scripts
- whether the change invalidates assumptions in any target item's body/spec/design_spec/technical_plan/worktree_plan

Produce a concrete landed-impact list:
- `These tickets need updating because X landed and changed Y.`
- Do not skip this step. This is the core value of feed.

## 1.7 Inspect Shared Surfaces And Hot Spots

For each target item, inspect the likely touched files, tests, docs, scripts, agents, and hook paths so you can identify real overlap and merge hot spots.

Focus on:
- shared files and hot write surfaces
- same contract / API / schema surfaces
- same prompt / agent / hook paths
- same generated artifact flow
- same test harness or deployment surface

## 1.8 Re-Read MASTER-PLAN.md Structure

Re-examine `MASTER-PLAN.md` specifically for generation/wave structure:
- Identify the current generation and its completion state
- Identify what the next generation/wave contains
- Identify which items from the plan are already materialized in the backlog
- Identify which items from the plan are not yet materialized (these are candidates for `materialize_new`)

## Context Produced

After this phase, the following context is available for subsequent phases:

- **SML content**: Full text of the required SML files when materialization analysis is in scope
- **Frontier items**: List of all non-terminal items with id, title, status, type, priority
- **Target item context**: Body/spec/design_spec/technical_plan/worktree_plan/shepherd_caveats for every target item
- **Dependency graph**: All dependency edges for target items, with source attribution
- **Recent landed change report**: Recent commits plus diff-stat summaries of what actually changed
- **Landed-impact updates**: A concrete list of target items that need updates because recent landed work changed their assumptions
- **Materialization gaps**: Items in MASTER-PLAN.md not yet represented in the backlog
