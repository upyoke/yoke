# Curate Phase: Cluster Entries And Route Them To An Output

This phase owns entry loading, clustering, code validation, duplicate checking, routing each cluster to a Dash or a work item, and reviewed/archive state updates for `/yoke curate`.

## 1. Read Unreviewed Ouroboros Entries From The DB

The shared entry reader is always bounded (default newest 50) so the
https relay cannot exceed its response size ceiling. Start with a count,
then page:

```bash
yoke ouroboros entry list --unreviewed --count
yoke ouroboros entry list --unreviewed --limit 50
yoke ouroboros entry list --unreviewed --limit 50 --offset 50
```

Each list response is a JSON object whose `entries` array carries one typed
record per entry (plus `limit` / `offset` for the page). A `--count` call
returns `{ "count": N }` instead of entry bodies:

- `id` — integer entry ID
- `timestamp` — when the observation was made
- `agent` — author label: the subagent role that logged it (`engineer`,
  `tester`, ...) or the harness executor for a top-level session
- `context` — epic/task or session context
- `category` — `problem`, `friction`, `idea`, `cross-critique`, or
  `field-note-{kind}` for the field-note channel
- `body` — observation content
- `reviewed_at` — empty for unreviewed entries
- `project` — project slug or empty for system-level observations
- `corrects` — entry this one supersedes, or empty
- `superseded_by` — entry that supersedes this one, or empty
- `promoted_dash` — the Dash this entry already produced, or empty

To filter by project:
```bash
yoke ouroboros entry list --unreviewed --project yoke --limit 50
```

Read one full entry by id (preserves newlines in `body`):
```bash
yoke ouroboros entry get {id}
```

Page until a page returns fewer than `--limit` rows (or `count` is
exhausted). Collect the working set for clustering from those pages —
do not request an unbounded list.

- If `entries` is empty on the first page: report "No new Ouroboros entries to review." and stop.
- If an entry record is malformed: log a warning and skip it.

## 2. Cluster Related Observations

Review all unreviewed entries and group them by semantic similarity:
- Same root cause -> one cluster
- Same improvement idea from different contexts -> one cluster
- Unrelated observations -> clusters of one

An entry carrying `promoted_dash` already produced its output — do not re-cluster it. An entry carrying `superseded_by` has been replaced; cluster the correction instead.

For each cluster, synthesize a summary that captures the core observation across all entries.

## 3. For Each Actionable Cluster, Validate Against Current Code, Check For Duplicates, And Propose An Output

### Optional session continuity context

Review recent item Progress Log entries and Ouroboros field-notes when they
provide useful context. If no relevant continuity exists, proceed without it.

### a. Duplicate check

Pass 1 — Title scan:
```bash
yoke items list --fields "id,title,status"
```

Pass 2 — Spec scan for near-misses and overlapping keywords:
```bash
yoke items get {N} spec
```

Classify each match as `[title match]`, `[body match]`, or `[scope overlap]`.

### b. Code validation

Before presenting the cluster, verify the problem still exists in the current codebase:

1. Extract specific file paths, function names, script names, config keys, or code patterns from the observation body.
2. Use Grep/Read to check whether the described problem is still present.
3. Check done items for likely overlap:
 ```bash
 yoke items list --status done --fields "id,title,status"
 yoke items get {N} spec
 ```
4. Assign one verdict:
 - **Still present**
 - **Likely resolved**
 - **Inconclusive**

### c. Size the output

Pick the smaller output that still covers the cluster:

- **Dash** — the cluster names one concrete repair a single session can carry out from a written instruction: a recipe naming the wrong flag, a stale doc reference, an unhelpful denial message, a missing `--help` body. This is the common case for field-note clusters.
- **Work item** — the cluster names a root cause that needs crafted acceptance criteria, design work, or more than one delivery slice.

### d. Resolve the filing contract

Resolve the cluster's target project before finalizing its proposed output.
Use workflow `dash` for a Dash and `issue` for a work item, then call the
registered `workflow.execution_instruction.resolve` read:

```bash
yoke workflow execution-instruction resolve \
 --workflow {dash|issue} --project {project}
```

Apply every returned instruction to the proposed title, Dash instruction, or
work-item body. The create receipt remains defense in depth, not the first
delivery point.

### e. Present the cluster

```text
Cluster {N}: {synthesized title}
Based on {count} observation(s) from: {agent list}
Category: {problem | friction | idea | cross-critique | field-note-{kind}}
Entry IDs: {comma-separated list}

Summary: {synthesized description}

Code validation: {Still present | Likely resolved | Inconclusive}
{validation details}

Proposed output: {dash | work item}
 Title: {title}
 Instruction / Priority: {instruction for a dash | low | medium | high}

Similar existing items:
 - PREFIX-{N}: {existing title} (status: {status})

Likely resolved -- recommend skip
 Evidence: {brief explanation}

Action? (create / skip / defer)
```

- `create` -> promote or file in step 4
- `skip` -> mark entries as reviewed without producing an output
- `defer` -> leave entries unreviewed for the next curate run

## 4. Produce Approved Outputs

### Dash — the default for field-note clusters

Promote the entry that best states the signal. The promotion creates the Dash, links it to the note, and marks that note reviewed:

```bash
yoke workflow execution-instruction resolve --workflow dash --project {project}
yoke ouroboros field-note promote {entry-id} \
  --title "{specific title}" \
  --instruction "{the complete requested scope, in one paragraph}"
```

The instruction defaults to the note's own body — pass `--instruction` when the cluster says more than any single note does. A note with no project needs `--project {slug}`; notes written after project attribution landed carry their own. Mark the cluster's other entries reviewed in step 5.

### Work item — for root causes

Invoke:

```bash
yoke workflow execution-instruction resolve --workflow issue --project {project}
yoke items create "{title}" issue --priority {priority} --entry-surface harness_skill --execution-instructions-considered
```

Immediately write a body with the cluster context:

1. Create a temp file containing:
 ```text
 # {work item title}

 ## Observation Summary
 {synthesized cluster summary}

 ## Source Entries
 - Entry IDs: {comma-separated entry IDs}
 - Agents: {comma-separated agent list}
 - Categories: {category or categories}

 ## Code Validation
 - Verdict: {Still present | Likely resolved | Inconclusive}
 - {validation details}

 ## File Budget
 UNRESOLVED — this work item creates/grows authored code but the file shape is not yet known. `/yoke refine` MUST resolve the expected implementation shape before this item advances past `refining-idea`.
 ```

When the target project's effective File Budget policy is required, that
UNRESOLVED marker is the minimum idea-status shape. `/yoke refine` resolves
it before the item leaves `refining-idea`. Include the section even when
the policy is currently optional — an extra documented deferral does not
fail optional-budget workflows.
2. Write the spec via the `items.structured_field.replace` function
   call (envelope in
   [`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
   `target = {kind: "item", item_id: <id>}`, `payload = {field: "spec",
   content: "<spec content>", source: "curate"}`. `items.body` is a
   virtual rendered field — writes always route through the structured
   `spec` field.
3. Verify the write succeeded by checking the response
   `success=true` and the
   `result.new_line_count` / `result.verification` fields.

If `gh` is available:
- Ensure the `source:ouroboros` label exists
- Tag the GitHub issue with that label

## 5. Mark Entries As Reviewed

For every entry examined during this curate run, mark it as reviewed:

```bash
yoke ouroboros entry mark-reviewed {id}
```

Entries where the operator chose `defer` should not be marked reviewed. A promoted entry is already marked reviewed by its promotion.

The entry's own project authorizes the write, so an id from another
project is refused rather than closed out under this checkout's project.

## 6. Archive Reviewed Entries

After marking entries as reviewed, archive all reviewed-but-not-yet-archived entries:

```bash
yoke ouroboros entry mark-archived --all-reviewed
```

The command returns the count of archived entries. It archives this
checkout's project (pass `--project P` to name another), and refuses to run
with no project rather than archiving every project's queue. Add
`--include-unattributed` to also cover entries that belong to no project.
