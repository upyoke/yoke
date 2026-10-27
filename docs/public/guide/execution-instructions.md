# Execution instructions

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Execution instructions
<!-- /yoke:breadcrumbs -->

Execution instructions are snippets of custom project-specific context that you and your agents configure through Yoke to reach the right agent at exactly the right time. They capture conventions, constraints, reminders, or procedures and can apply to selected projects, workflows, and workflow stages.

Manage instructions through your agent or the Workflows dashboard page. During `/yoke onboard`, your agent can help identify and configure the instructions your first work needs.

## Instruction content

Write the action an agent should take and enough context to do it correctly. For example: “For interface changes, review keyboard navigation and visible focus before completing implementation review.” Link to maintained project documentation when the full procedure is longer.

Instructions supply reusable context. An item's specification and acceptance criteria still describe that item's own requirements. Yoke keeps applicable instructions separate from the item body.

This follows [progressive disclosure](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills): provide relevant detail when it is needed rather than putting every rule into every interaction.

## Project and workflow scope

Choose the projects and workflows that should receive an instruction. An instruction may apply to all projects, all workflows, or selected combinations. Broad scope is useful for a genuine shared convention; project-specific deployment or account details belong in appropriately restricted project guidance.

Scope controls which work matches. Delivery settings control when the matched instruction is supplied.

## Delivery points

| Delivery point | Use |
|---|---|
| Before creation | Context the agent needs before filing work |
| On every read | Context that remains relevant while inspecting and carrying out the item |
| When entering stage | Context needed when work reaches selected parts of its workflow |

New instructions default to Before creation and On every read. At least one delivery point is required. Stage delivery also requires at least one stage bucket.

## Stage buckets

Stage buckets group equivalent parts of different workflows: idea, planning, refined, implementing, reviewing, implemented, and release. Instructions target these buckets rather than requiring a separate rule for every custom stage name.

The item's pinned workflow defines each stage's bucket. A review instruction can therefore reach an item when it enters the reviewing bucket even if that workflow uses its own stage identifier.

## Creating and editing instructions

In the Workflows dashboard page, use the Execution instructions panel to create or edit the content, scope, and delivery settings. The panel shows the current selections together so you can see which work receives the instruction.

You can also ask your agent to manage instructions through `yoke workflow execution-instruction`. Editing prose preserves scope and delivery settings unless the edit explicitly changes them. Read the command's help for the supported options.

## Instruction resolution

Before filing, agents resolve instructions for the selected project and workflow. Item reads return the applicable read instructions and matching stage instructions. Work-claim acquisition and composed worker launches provide the full applicable instructions to the receiving agent.

Successful stage transitions return the instructions for the entered stage. Narrow reads may name the applicable instructions and point to the full read rather than repeating all the text.

Your agent can inspect the resolved set to check a rule's scope and delivery. This is useful when an instruction appears unexpectedly or fails to reach the work you intended. [Delivery and resolution reference](../projects/execution-instructions.md)

## Instruction ownership

Keep project-specific policy in project instructions and maintained project documentation. Keep reusable Yoke product guidance in its public documentation or agent operation home, with a concise link from an instruction when needed.

Avoid copying long procedures into several instructions. Updating one maintained source is more reliable than correcting multiple stale copies. See [Agent guidance](guidance.md), [Projects](configuration.md), and [Workflows and work items](work.md).
