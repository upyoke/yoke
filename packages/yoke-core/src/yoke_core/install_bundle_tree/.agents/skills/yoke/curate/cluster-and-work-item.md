# Curate — Cluster and File

## 1. Read a bounded queue

Field-notes are the primary channel; use the indexed dedicated reader when
curating them. For a mixed queue use the shared entry reader. Count first,
then page in batches of 50; both default to newest 50 with no time window:

```sh
yoke ouroboros field-note list --unreviewed --count
yoke ouroboros field-note list --unreviewed --limit 50
yoke ouroboros field-note list --unreviewed --limit 50 --offset 50
yoke ouroboros entry list --unreviewed --count
yoke ouroboros entry list --unreviewed --limit 50
yoke ouroboros entry list --unreviewed --limit 50 --offset 50
yoke ouroboros entry get {id}
```

A bare list uses the checkout's project; `--project P` selects another.
List JSON carries `entries`, `limit`, `offset`; count returns `count`.
Typed records carry id, timestamp, agent, context, category, body, project,
reviewed_at, corrects, superseded_by and promoted_dash. Categories include
problem/friction/idea/cross-critique and field-note kinds. Read full bodies
by id when needed. Stop paging on a short page or exhausted count.
Empty first page: “No new Ouroboros entries to review.” Malformed entry:
warn and skip.

## 2. Cluster

Group the same root cause or improvement across contexts; unrelated signals
stand alone. Already-promoted entries have their output; skip them.
A correction's `corrects` link supersedes the older note: cluster the correction
rather than both. Unlinked duplicate/restatement notes belong together and
are both reviewed when handled.

Optional current Progress Logs/field-notes may supply context; proceed when
none is relevant. Corroborating events start narrow:

```sh
yoke events query --event-name {EventName} --project P --since "2 days ago" --limit 20
```

Widen only after a useful result. Multi-day anomaly sweeps return full
envelopes and are unsuitable queue browsing.

## 3. Validate and propose

Scan current item titles, then specs for near misses; classify matches as
title match, body match or scope overlap. Check done-item overlap too:

```sh
yoke items list --fields "id,title,status"
yoke items get PREFIX-N spec
yoke items list --status done --fields "id,title,status"
```

Extract the observation's paths, functions, scripts, keys and patterns;
verify them in current code. Classify Still present, Likely resolved or
Inconclusive with evidence. One repair executable from a complete instruction
is Dash; acceptance agreement or generated parallel lanes calls for an item.
Volume alone does not change that choice.

Resolve the target project and read all filing instructions before drafting:

```sh
yoke workflow execution-instruction resolve --workflow {dash|issue} --project {project} --full
```

Apply every returned instruction before the effect; the create receipt is
defense in depth. Present each cluster's title, count/authors/category/entry
ids, summary, code verdict/proof, proposed output/title/instruction or priority,
and similar items with refs/status. Recommend skip with evidence for likely
resolved work. Ask `create / skip / defer`: create routes below, skip reviews
without output, defer keeps entries unreviewed.

## 4. Produce approved outputs

For Dash, promote the representative field-note:

```sh
yoke ouroboros field-note promote {entry-id} --title "{specific title}" --instruction "{complete scope}"
```

Promotion links the output and reviews that note. Instruction defaults to its
body; override when the cluster has broader scope. A note with no project
requires `--project {slug}`; attributed notes use their own project.
Review the other handled cluster entries below.

For a work item, use the issue workflow's authorized `harness_skill` filing
contract, the same contract `/yoke idea` uses. After the full instruction read,
create once:

```sh
yoke items create "{title}" issue --priority {priority} --entry-surface harness_skill --execution-instructions-considered
```

Immediately write the spec through `items.structured_field.replace`:
target `{kind: "item", public_ref: "PREFIX-N"}`, payload
`{field: "spec", content: "<full spec>", source: "curate"}`.
Use [typed envelopes](../idea/body-and-sync-functions.md).
The spec includes observation summary, source entry ids/authors/categories,
code verdict/evidence and File Budget. Mark unknown authored-file shape
`UNRESOLVED`; Refine must resolve it before leaving `refining-idea`.
Include that deferral even when budget is optional. Verify `success=true`,
`result.new_line_count` and `result.verification`; virtual body is read-only.
When gh is available, ensure `source:ouroboros` exists and tag the resolved
`github_issue`, rather than treating a public ref as an issue number.

## 5–6. Review and archive

Mark each handled entry, except deferred entries or a promoted note already
reviewed by promotion:

```sh
yoke ouroboros entry mark-reviewed {id}
yoke ouroboros entry mark-archived --all-reviewed
```

Review timestamps prevent repeated processing; archive immediately and retain
DB history. A named id is authorized by its own project. Unnamed selectors
(`--all-reviewed`, `--before`, `--field-notes-before`) target the checkout
project or explicit `--project P` and refuse without one. Unattributed entries
remain unless `--include-unattributed` explicitly includes them. Record the
archive receipt count; then return to the retrospective in run.md.
