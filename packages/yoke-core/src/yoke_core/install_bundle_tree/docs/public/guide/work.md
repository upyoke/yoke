# Workflows and work items

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Workflows and work items
<!-- /yoke:breadcrumbs -->

A workflow defines the stages work moves through and the checks required to move forward. A work item follows one workflow and records its intended outcome, plan, progress, and evidence. Ask your agent to file and manage items; use the dashboard to follow the work and make decisions.

## Stages, gates, and workflow configuration

A **stage** says where an item is in its workflow. A **transition** moves it to another stage. A **gate** defines what must be true before that transition can happen, such as completing a review, passing QA, or receiving approval.

<!-- yoke:visual workflow -->

### Built-in workflows

| Workflow | Suitable work |
|---|---|
| Dash | Direct execution from a written specification, including substantial changes |
| Issue | A bounded change that needs refinement before implementation |
| Epic | Work that benefits from a plan with generated implementation tasks |
| Blitz | Substantial work organized around a linked strategy document |

Choose by how the work should be organized, not just by its size. The Workflows dashboard page shows the actual stages and checks for each definition. [Workflow reference](../workflows/index.md)

### Versions and defaults

An item pins a workflow version when it is created. Publishing a new definition changes the default for new items; existing items retain their pin until explicitly migrated. This keeps an in-progress item's rules stable.

Project defaults select testing and delivery behavior. Workflow policy controls approvals and execution posture. Posture settings cover matters such as verification, file budgets, worktree isolation, path claims, and delivery requirements. Settings can tighten permitted behavior without removing core gates.

### Approvals and execution levels

An approval policy names the roles or people who may decide and whether any one approver or all required approvers must answer. A rejection remains a decision to resolve, not a missing approval to ignore.

Stage defaults choose an execution level, which determines the model and effort used for that stage. An item's effective configuration may include permitted overrides. See [Steering and fleet control](sessions.md) for levels and staffing, and [lifecycle rules](../workflows/lifecycle.md) for the exact configuration contract.

## Describe and manage an item

### Outcome, acceptance criteria, priority, and scope

An item should explain what should change and how someone will know it worked. Acceptance criteria make the intended result concrete. Priority helps the scheduler order eligible work; it does not bypass dependencies or required checks.

Keep the scope complete enough to deliver the result. If a change needs another project's code, coordinate the related work explicitly rather than hiding it in the first item's description.

### Item body and stored fields

The readable body brings together structured fields such as the specification, plan, and progress log. Agents update these through Yoke's item commands, so the rendered body and the stored facts stay consistent. A Progress Log records current state and handoffs; it does not replace acceptance criteria or QA evidence.

Ask your agent to amend the item when the intended work changes. Cancel work that is no longer wanted through its lifecycle, preserving its history. [Item reference](../items/index.md)

## Dependencies and blocked work

A dependency records that one item must wait for another at a particular point. Work may need to wait before starting, before merging, or before closing. The items can belong to different projects.

A block records another reason work cannot proceed. A freeze deliberately keeps work from being scheduled. Both preserve the item's current stage. The named owner or steering agent resolves the cause and updates the relevant record; changing a label is not evidence that the obstacle is gone.

See [The Frontier](frontier.md) for dependency graphs, readiness, and scheduling.

## Epics and generated tasks

An Epic holds the shared outcome and integration responsibility. Its plan can generate tasks, each with its own implementation responsibility and dependencies. Tasks are part of the parent workflow rather than unrelated items that happen to share a title.

Planning establishes the task boundaries, implementation progresses those tasks, and integration checks that the combined change meets the parent goal. A completed task does not by itself prove the whole Epic is ready to deliver. [Generated task reference](../items/model/tasks.md)

## Worktrees and work ownership

A **worktree** is an isolated checkout for a change. A **lane** is the working location associated with an item's execution. A **work claim** records which session owns the work; a **path claim** coordinates files when the workflow requires it.

Claims help agents avoid conflicting assignments. Overlapping work may need an ordering dependency or an explicit coordination decision. A handoff transfers responsibility with recorded state rather than relying on a private conversation's memory.

Cleanup follows the workflow's completion process. It must preserve unfinished work and evidence needed for recovery. [Worktrees and claims](../agents/rules/lanes-and-claims.md)

## Review and merge

Review checks the implementation against its requirements. Merge checks establish that the change can land, including configured CI and merge-queue requirements. Landing records connect the item to the code that actually merged.

Merging and deployment are separate events. An item whose workflow requires delivery remains accountable for that delivery and its QA after merge. See [Deployments and releases](delivery.md) and [merge-queue landings](../github/merge-queue-landings.md).
