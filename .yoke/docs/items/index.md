# Items

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Items
<!-- /yoke:breadcrumbs -->

Read and update backlog work and its effective completion flow.

## Items

Workbench **Items** lists backlog work. Open an item for status, fields,
progress, claims, and QA attachments.

New Item keeps a draft through refresh in the same browser tab when session
storage is available. Drafts belong to the signed-in actor and universe;
restoration rechecks the project's creation permissions and workflow settings.
Retry preserves typed fields. Creation clears only the submitted draft; edits
made while creation is pending remain available. A response from a form you
have left cannot navigate you away or erase a newer draft. **Discard draft**
explicitly abandons it. Closing the browser session can remove it.

Narrow layouts show labeled item cards with every sort choice available
above them. Item details place status, ownership, blockers and delivery facts
ahead of long narrative on a phone; the desktop keeps its two-column layout.

The table starts with **Last updated, descending** when the signed-in actor
has no saved sort. Column headers change the sort for the full filtered
dataset before pages load; equal values have a stable item-ID tie break.
The actor's column and direction are saved on the server independently of
project selections and restored across browsers, devices, and reloads.
Returning to Items or bringing its tab back into focus refreshes that choice.
Load or save failures show recovery guidance beside the table; a failed read
keeps the last known order and never saves a default over the stored choice.

```bash
yoke items get PREFIX-N
yoke items get PREFIX-N body
yoke items progress-log append PREFIX-N --headline TEXT --content TEXT
```

The default read returns metadata, stored fields and item sections once;
request `body` for the composed document. Human output omits empty fields and
sections. `--json` retains empty values and complete execution instructions.

`yoke items search KEYWORDS` returns up to 20 matches across statuses, with
the remaining count. Use `--limit N` (1–1000) to read more. JSON retains each
returned row's complete facts and `total_count` for the authorized scope.

Writes go through structured fields and registered functions — not raw body
files. See [agents/commands.md](../agents/commands.md).

## Effective completion flow reads

`yoke items get PREFIX-N deployment_flow` resolves the item's selected flow
or its project workflow default and prints the source, for example
`flow-name (project default)`. Read `--help` for the field projection.
The JSON field is `{value, source}`; sources are `item`, `project_default`,
`none`, or `unreadable`. Item listings and detail views carry the same
effective value and provenance. An unreadable default stays named rather
than appearing to be an unconfigured item.

`yoke deployment-flows list` keeps each stored stages document in one row;
JSON preserves the complete stored value and text renders stages compactly.
Read `--help` for project and disabled-flow filters.


## Related

- [Sessions](../sessions/index.md)
- [Inbox and messaging](../sessions/inbox.md)

<!-- yoke:contents -->
- [Item model](model/items.md) — Read item fields, database claims and supporting records.
- [Item dependency model](model/dependencies.md) — Read dependency edges, gate satisfaction and the canonical blocker model.
- [Generated task model](model/tasks.md) — Read task graphs, dispatch chains and progress records.
- [Landing model](model/landings.md) — Inspect merge provenance and landing attribution.
<!-- /yoke:contents -->
