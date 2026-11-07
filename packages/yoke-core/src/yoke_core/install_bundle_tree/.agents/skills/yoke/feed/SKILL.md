---
name: feed
description: "Refresh stale frontier items, reconcile Feed's dependency edges, and file new work from strategy."
argument-hint: "[--no-new-items] [PREFIX-N ...] [--model MODEL]"
---

# /yoke feed

Refresh stale items and Feed's dependency rows; file strategy work.

`--no-new-items` creates nothing; `PREFIX-N` args set the focus. Claim first;
every exit after acquiring releases FEED:

```text
yoke claims work acquire --process FEED --project <project> --reason feed_run
yoke events emit --name FeedStarted --kind lifecycle --type feed --source-type skill --severity STATUS --outcome started --project <project>
```

Phase map: [gather.md](gather.md), [decide.md](decide.md),
[materialize.md](materialize.md), [reconcile.md](reconcile.md).
