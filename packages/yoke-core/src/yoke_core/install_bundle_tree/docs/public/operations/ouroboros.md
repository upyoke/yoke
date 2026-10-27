# Ouroboros

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Operations](index.md) > Ouroboros
<!-- /yoke:breadcrumbs -->

Record observations and use the learning loop to improve delivery.

## Ouroboros

Self-improvement loop: field-notes and observations → curate → doctor →
simulate. Workbench **Ouroboros** surfaces entries and field-notes.
Each row links a bounded evidence preview to the complete note. The roster
reads only the preview, keeps newest-first paging, and labels review/category
filters; opening a note retrieves the full evidence.

```bash
yoke ouroboros field-note append --kind observation --evidence '...'
 /yoke curate
```

For a repeat, pass `--correlation-id ROOT_ID` with the first note's integer id.
The note stores that root and the filing session durably. Unreviewed lists and
counts include root problems only; root reads show a repeat count and the latest
20 evidence previews. Open a repeat by id for its complete evidence; ordinary
lists page through all notes.

A wrong or missing recipe belongs here; a successful routine recovery and
progress narration belong in the item's **Progress Log**.

Curation is operator-run. Once a week, the steering operator runs `/yoke curate`
for each project with an open queue and records the review date, remaining count
and next review date in the claimed strategy document. Steering checks this
checkpoint each pass and surfaces an overdue review. Curate verifies causes
against shipped work, records the covering item for each handled set, then
reviews and archives those notes through the existing entry commands.


The Ouroboros dashboard labels filing timestamps as **Filed at** and defaults to newest first. Observation, project, Filed at, Category, Context and Reviewed headers sort the matching roster before cursor pagination. Sort choices use the existing actor/universe preference store and restore across browsers and devices. The repetitive executor column is omitted; complete entry details remain available. Narrow layouts expose labeled row values and keep sort controls available.

## Related

- [Doctor](doctor.md)
- [Events](events.md)
