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
landed_at TEXT NOT NULL -- when it landed; see origin
origin TEXT NOT NULL DEFAULT 'recorded' -- recorded | reconstructed
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

**`origin` says what `landed_at` promises.** Close-out writes
`origin='recorded'`. A git-history backfill writes `origin='reconstructed'`:
every other column is what git stated, and `landed_at` is the merge commit's
committer time. For a merge-queue landing that time runs minutes early of the
GitHub-observed moment -- the queue creates the commit when the train forms
and merges it later -- which the repository cannot recover. Treat a
reconstructed timestamp as approximate; treat a recorded one as the moment
close-out stored.

**One live writer, plus the backfill.** Rows that happen after the table
exists are appended at the merge close-out boundary
(`yoke_core.domain.item_landings_close_out`), which both routes to the base
branch pass through. History that predates that writer is inserted by the
governed backfill, which calls the same `landing_route` classifier and the
same append, keyed on `(item_id, merge_sha)`, so a merge close-out already
recorded is left untouched. The append is idempotent on that key: a close-out
re-entered after a dead wait converges on the landing it already recorded.

Read them with `yoke item-landings list PREFIX-N`, which also names the
release that delivered each landing, or that none has, and whether the
timestamp is recorded or reconstructed.

Back to [items-and-epics.md](items-and-epics.md).
