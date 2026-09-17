# /yoke curate — the curation sequence

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active curate). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode curate
```

**Read and follow [cluster-and-work-item.md](cluster-and-work-item.md).** That file covers loading unreviewed entries, clustering, validating clusters against code and existing backlog items, routing each cluster to a Dash or a work item, and marking reviewed/archived entries.

Close the run with a retrospective in chat:

```text
# Ouroboros Retrospective

## Entries Processed
- Total entries examined: {N}
- By category: {category: count, ...}
- By author: {agent: count, ...}

## Clusters
- Clusters formed: {N}
- Dashes promoted: {N} ({PREFIX-N, ...})
- Work items filed: {N} ({PREFIX-N, ...})
- Entries skipped: {N}
- Entries deferred: {N}
- Clusters flagged as likely resolved: {N}

## Archiving
- Entries archived: {N}
- Entries remaining (unreviewed): {N}
```

## Notes

- This command is operator-invoked only. There is no auto-trigger.
- Entries are read through the registered Ouroboros readers with paging, for example `yoke ouroboros entry list --unreviewed --limit 50` (use `--count` and `--offset` for large queues). A bare list attaches the checkout project the same way the writers do; pass `--project P` to name another.
- Mark reviewed entries through the registered lifecycle writer:
  `yoke ouroboros entry mark-reviewed {id}`.
- The `reviewed_at` timestamp mechanism ensures entries are only processed once (unless deferred). Promoting a note marks it reviewed as part of the promotion.
- Reviewed entries are archived immediately via
  `yoke ouroboros entry mark-archived --all-reviewed` — they remain in
  the DB but no longer appear in unreviewed queries.
- Both writers are project-scoped. A named entry id is authorized by that
  entry's own project, so a run in one checkout can't close out another
  project's queue. A selector that names no entry — `--all-reviewed`, or a
  `--before` / `--field-notes-before` cutoff — runs against the checkout's
  project (or `--project P`) and refuses without one. Entries that belong to
  no project are left alone unless the selector adds
  `--include-unattributed`.
- Recurring cross-run patterns live in `ouroboros/patterns.md` as institutional memory. Add to it when a cluster genuinely names a new recurring shape — not as a per-run step.
- Interactive filing goes through `/yoke idea`; this Yoke-owned workflow uses the issue workflow's authorized `harness_skill` entry surface so claims and GitHub sync stay on the product flow.
- This is part of Ouroboros — Yoke's self-improvement system. The learning loop: agents observe -> log to DB -> curate -> Dash or work item -> fix -> agents observe better.
