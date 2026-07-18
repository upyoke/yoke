# Curate Phase: Cluster Entries And File Tickets

This phase owns entry loading, clustering, code validation, duplicate checking, ticket filing, and reviewed/archive state updates for `/yoke curate`.

## 1. Read Unreviewed Ouroboros Entries From The DB

```bash
yoke ouroboros entry list --unreviewed
```

This returns a JSON object whose `entries` array carries one typed
record per entry:

- `id` — integer entry ID
- `timestamp` — when the observation was made
- `agent` — which agent logged it
- `context` — epic/task or session context
- `category` — `problem`, `friction`, `idea`, or `cross-critique`
- `body` — observation content
- `reviewed_at` — empty for unreviewed entries
- `project` — project slug or empty for system-level observations

To filter by project:
```bash
yoke ouroboros entry list --unreviewed --project yoke
```

Read one full entry by id (preserves newlines in `body`):
```bash
yoke ouroboros entry get {id}
```

Collect all entries into a working set for clustering.

- If `entries` is empty: report "No new Ouroboros entries to review." and stop.
- If an entry record is malformed: log a warning and skip it.

## 2. Cluster Related Observations

Review all unreviewed entries and group them by semantic similarity:
- Same root cause -> one cluster
- Same improvement idea from different contexts -> one cluster
- Unrelated observations -> clusters of one

For each cluster, synthesize a summary that captures the core observation across all entries.

## 3. For Each Actionable Cluster, Validate Against Current Code, Check For Duplicates, And Propose A Ticket

### Optional wrapup context

```bash
yoke ouroboros wrapup list
```

If wrapup reports exist, use them as additional context. If the query returns no results or fails, proceed without them.

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

### c. Present the cluster

```text
Cluster {N}: {synthesized title}
Based on {count} observation(s) from: {agent list}
Category: {problem | friction | idea | cross-critique}
Entry IDs: {comma-separated list}

Summary: {synthesized description}

Code validation: {Still present | Likely resolved | Inconclusive}
{validation details}

Proposed ticket:
 Title: {ticket title}
 Type: issue
 Priority: {low | medium | high}

Similar existing items:
 - YOK-{N}: {existing title} (status: {status})

Likely resolved -- recommend skip
 Evidence: {brief explanation}

Action? (create / skip / defer)
```

- `create` -> create the ticket in step 4
- `skip` -> mark entries as reviewed without creating a ticket
- `defer` -> leave entries unreviewed for the next curate run

## 4. Create Approved Tickets (With Mandatory Body)

For each `create` response, invoke:

```bash
yoke items create "{title}" issue --priority {priority} --idea-intake
```

Immediately write a body with the cluster context:

1. Create a temp file containing:
 ```text
 # {ticket title}

 ## Observation Summary
 {synthesized cluster summary}

 ## Source Entries
 - Entry IDs: {comma-separated entry IDs}
 - Agents: {comma-separated agent list}
 - Categories: {category or categories}

 ## Code Validation
 - Verdict: {Still present | Likely resolved | Inconclusive}
 - {validation details}
 ```
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

Entries where the operator chose `defer` should not be marked reviewed.

## 6. Archive Reviewed Entries

After marking entries as reviewed, archive all reviewed-but-not-yet-archived entries:

```bash
yoke ouroboros entry mark-archived --all-reviewed
```

The command returns the count of archived entries.
