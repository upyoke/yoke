# Strategy docs

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Strategy docs
<!-- /yoke:breadcrumbs -->

Strategy documents are Markdown text stored in your Yoke Universe's database that you and your agents can create, edit, and archive. They keep project direction and the rolling plan available across sessions, while work items track implementation and delivery.

## Standing strategy docs

MISSION, VISION, LANDSCAPE, and MASTER-PLAN give humans and agents a shared understanding of the foundational context in which a project operates.

<!-- yoke:visual strategy-pyramid -->

| Document | Purpose |
|---|---|
| MISSION | Why the project exists |
| VISION | The future state you want to reach |
| LANDSCAPE | External context, research, and relevant alternatives |
| MASTER-PLAN | The evolving strategy for getting there |

These documents provide context for choosing work. Keep them focused on direction and durable knowledge rather than using them as a second item tracker.

## Working strategy docs

CURRENT-PLAN and other working strategy docs you create hold major initiatives, big slices of work, and ideas not yet filed as work items. They connect ideation to the work your agents are carrying out.

<!-- yoke:visual strategy-work -->

Your agent files work items to track implementation and delivery, keeping the strategy doc updated with what's filed, what remains, and current progress. A paragraph in a strategy doc does not execute on its own; Yoke's work items and workflows provide that execution path.

A working document can be the scope of a steering seat. Its linked items then identify the work that seat coordinates. Project-wide steering can instead cover the whole project while using a working document as its standing plan.

See [Steering and fleet control](sessions.md) and [The Frontier](frontier.md).

## Create, edit, and archive strategy docs

Ask your agent to create or update a document, or use `/yoke strategize` for a guided strategy conversation. Review the corpus and its history on the dashboard's **Strategy** page.

The database is authoritative. Files rendered into `.yoke/strategy/` are local working views, not an independent copy to commit as project truth. The strategy commands support rendering, editing, and ingesting a document through the expected update path.

Archive a document when it is no longer active but its context should remain available. Archiving removes it from the active corpus without deleting its history. Focused documents can supplement the standing set without replacing it.

The [strategy reference](../strategy/index.md) covers document commands, local rendering, and item links.

## Keep plans current and resume work

As work progresses, the working document should explain the current objective, completed and pending work, key decisions, and the next useful action. Item links let a new session inspect the authoritative state rather than relying on a prose status that may be old.

Work can be safely stopped and resumed anytime, from anywhere, without loss of any critical context when that context has been recorded in the shared plan and work records. Preserve decisions and unresolved questions there before ending a conversation.

Changing a plan does not automatically cancel, reassign, or rewrite every linked item. Your agent updates the relevant work records as part of carrying the new direction into execution.
