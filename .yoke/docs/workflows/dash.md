# Dash

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Workflows](index.md) > Dash
<!-- /yoke:breadcrumbs -->

Dash executes a written specification through survey, isolation,
implementation, verification, merge, and recorded evidence. It can cover a
substantial change when the outcome is clear.

## File or execute

Ask your agent to run `/yoke dash "specification"`, or
`/yoke dash PREFIX-N` for an existing item.
The agent follows the skill bound to the item's live workflow stage.

The specification should state the outcome, full scope, and acceptance
evidence. Dash surveys every touched file and uses the lane required by the
pinned workflow. See [Workflows and work items](../guide/work.md).

## Verify and land

The executing session checks the result and records evidence. Use
[`yoke merge item`](../github/merge-item.md) to land the lane and record
its result and verification together.

Merge and deployment are separate facts. An item that owes delivery waits
at release until its flow and QA obligations are satisfied. Read the command's
returned wait state rather than assuming merge means done.
