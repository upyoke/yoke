# Table: merge_queue_landing_attempts

A pull request opened for an item that already landed. The item's
`merge_queue_*` columns keep naming its current landing while the attempt is
in flight; the landing observer moves them onto the attempt only when GitHub
reports it merged. See
[Re-landing an item that already landed](../merge-queue-landings.md#re-landing-an-item-that-already-landed).

```sql
item_id INTEGER NOT NULL -- FK → items(id)
project_id INTEGER NOT NULL -- FK → projects(id)
pr_number TEXT NOT NULL -- the attempt's pull request
enqueued_at TIMESTAMPTZ -- the attempt's arming episode; NULL until armed
opened_at TIMESTAMPTZ NOT NULL -- when the merge boundary first recorded it
closed_at TIMESTAMPTZ -- NULL while the attempt is in flight
closed_reason TEXT NOT NULL DEFAULT '' -- merged, superseded, closed unmerged, or cleared at close-out
PRIMARY KEY (item_id, pr_number)
```

A partial unique index keeps at most one open attempt (`closed_at IS NULL`)
per item. Rows are kept after closing so the reason stays readable through
`yoke items detail get` under `merge_queue.attempt`.

The table is additive and converges on boot; it needs no governed migration.
