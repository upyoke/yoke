# Table: item_landings

Every landing an item has made, appended and never replaced. The item's own
columns -- `merged_at` and the four `merge_queue_*` markers -- each hold one
landing, the newest, so an item that landed four times in one day is
indistinguishable there from one that landed once, and no landing can be
audited afterwards. This table is where each one stays.

```sql
id INTEGER PRIMARY KEY -- monotonic; the tiebreaker for "the newest landing"
item_id INTEGER NOT NULL -- FK → items(id)
merge_sha TEXT NOT NULL -- the landing identity; see below
candidate_sha TEXT NOT NULL DEFAULT '' -- the lane commit the landing carried
pr_number TEXT NOT NULL DEFAULT '' -- the pull request, when one carried it
target_branch TEXT NOT NULL DEFAULT '' -- the base branch it landed on
route TEXT NOT NULL -- merge_queue | standalone | fast_forward
landed_at TEXT NOT NULL -- when it landed
UNIQUE (item_id, merge_sha)
```

**The row is keyed on the merge commit.** Delivery is asked in commit terms --
carried-work ranges and release-candidate ancestry are both commit-based --
while a pull request number is a provider label and a landing time is a time.
A fast-forward or squash that leaves no distinct merge commit records the
landed commit as its `merge_sha` and says `route='fast_forward'`, so a row is
never keyless. `candidate_sha` stays beside it rather than collapsing into it:
a landing recorded before its merge commit resolved has only that.

**`id`, not `landed_at`, orders the landings.** Two landings can share a
timestamp, so a reader asking which landing an item is currently answerable
for takes the highest `id`.

**One writer.** The rows are appended at the merge close-out boundary that
already resolves the landing identity
(`yoke_core.domain.item_landings_close_out`), which both routes to the base
branch pass through, so the record cannot drift from what close-out believes
it landed. The append is idempotent on `(item_id, merge_sha)`: a close-out
re-entered after a dead wait converges on the landing it already recorded.

Read them with `yoke items landings list PREFIX-N`, which also names the
release that delivered each landing, or that none has.

Back to [items-and-epics.md](items-and-epics.md).
