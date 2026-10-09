# Strategize — approved writes, implications and carry decisions

Aborted: entry release contract; no Finalize. Deferred-all: no strategy writes
or frontier checks; emit changes_deferred and capture pending carry decisions
below before Finalize.

## Write one approved document at a time

```sh
yoke strategy doc get <SLUG> --json
yoke strategy doc replace <SLUG> --content-file <scratch-path> --base-updated-at "<current-updated-at>" --target-root <repo-root>
```

Read current content/base, apply ALL approved changes for this doc to scratch,
then replace with that CAS token. Read selected write help first. Each write
changes only the named DB row and refreshes the full rendered corpus.
`replace_conflict`: fresh read/reapply approved changes/current base, never
retry stale base. Preserve another writer's new content; new decisions need
approval before expanding scope.

Check old_bytes/new_bytes/new updated_at against intended size, then read back:
intended changes/no loss or corruption/structure intact. Verification failure
returns to fresh read/reapply. Mission requires an approved entry AND explicit
confirmation at normative filter/change approval; otherwise skip with
“MISSION changes require explicit operator approval.”

Actual changed rows are the durable landing; caches have no git commit.
Record files_changed/applied count from successful writes.

## Checkpoint 4 — frontier implications

Read this project's planned/in-flight frontier. Present landed changes,
each affected item's alignment/relevance/urgency, new gaps and unaffected work.
Plain chat acknowledgment (`cp4:acknowledged`) continues; concerns trigger
discussion/re-presentation until acknowledged.

## Checkpoint 5 — only unresolved tradeoffs

Present only when ambiguity remains: multiple needs-review items, conflicting
priorities or checkpoint-4 concerns. Offer 2–3 paths/tradeoffs with semantic
labels, e.g. `finish_current_generation_first`,
`resequence_frontier_after_update`. Discuss until chosen; freeform alternative
requires confirmed label/description. `_tradeoff_resolution` is a semantic
string, never a numeric index; omit this checkpoint when no tension remains.

Emit SMLChangeApproved (lifecycle/strategize/skill, STATUS/completed/project):
files_changed, changes_applied, changes_deferred, outcome
changes_applied|changes_deferred. Deferred uses empty files, zero applied.

## Pending landed-work resolutions

If pending carry is empty, skip. Otherwise show the observed pending records'
public ref/title/priority/first_seen_at/age in chat; accept reflected,
dismissed: reason, or defer and normalize exact public refs into
`_reflected_item_ids`, `_dismissed_item_ids`, `_dismissed_reason`.

- Applied-path reflected MUST map to an actually applied SML change; if not
  mentioned, ask one clarifier before recording.
- Deferred sessions cannot mark reflected; allow dismissed/defer only.
- Defer is a no-op, in neither list; pending survives for later sessions.

Pass actual files/counts/outcome, carry decisions/reasons, approved/deferred
text and optional semantic tradeoff resolution to Finalize.
