# Yoke web dashboard

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Yoke web dashboard
<!-- /yoke:breadcrumbs -->

The web dashboard shows what is happening across your Universe and what needs your attention. Use it to follow strategy and work, inspect agent sessions, review QA evidence, and respond to messages and approvals.

## Open the dashboard and connect to your Universe

| Mode | Open the dashboard |
|---|---|
| Local and self-hosted | Run `yoke ui up` in your Terminal. |
| Hosted | Sign in at [app.upyoke.com](https://app.upyoke.com), currently in private beta. |

For a self-hosted connection, `yoke ui up` opens company sign-in when configured or creates a short-lived sign-in link for your connected identity. Run it on a machine with a browser. If the link expires, run the command again.

Check the selected Universe and project scope before taking action. A local dashboard reads that computer's Universe; a connected server dashboard reads the shared server's records.

## Navigate projects, strategy, and work

**Strategy** shows the planning documents that guide work. **Frontier** shows work that is waiting, ready to advance, active, or recently completed. These views answer different questions: strategy records direction and the rolling plan; items record the work that has been filed.

Open an item for its requirements, workflow stage, ownership, and evidence. Project filtering helps narrow a shared Universe to the work you want to inspect.

See [Strategy docs](strategy.md), [The Frontier](frontier.md), and [Workflows and work items](work.md).

## See active sessions and work ownership

**Sessions** shows coding-agent conversations, their liveness, steering scope, and held work. **Machines** shows the computers available to the Universe and their relay state.

A parked session may still own an item. Its silence does not mean the item is free to claim. Session cards distinguish liveness from the item's own blocked or frozen state and provide messaging where supported.

See [Steering and fleet control](sessions.md) for these states and recovery.

## Review QA evidence and deployment progress

**Shipping** brings together deployment progress, carried items, QA evidence, and approvals. **Deployments** lists reusable flows and their individual runs. A run page shows stages, results, work carried, and decisions.

**QA activity** shows recorded checks and their results. Open the case or evidence to inspect screenshots, command output, and earlier attempts. Evidence may be held on a particular machine; the dashboard identifies that situation rather than pretending it has a remote copy.

See [Quality assurance](qa.md) and [Deployments and releases](delivery.md).

## Respond to messages, questions, and approvals

**Inbox** separates decisions waiting on you from messages sent to you. A decision card states the request, its subject, what approving does, and who may answer it.

Approving one decision settles that decision only. Item work approval, QA evidence review, and run approval can be separate requirements. Their evidence and prior answers remain visible for traceability.

You can message a session from its card. Some sessions receive the message on their next operator-driven turn rather than waking immediately; the card states when delivery is queued.

See [Inbox and messaging](../sessions/inbox.md) for the detailed behavior.

## Find settings and access controls

Use project settings for project configuration, **Workflows** for workflow policy and execution instructions, and **Team** for people and access. **Capabilities** is a readiness inventory; capability creation and configuration happen through your agent or the CLI.

The dashboard does not expose every administrative operation. For example, the database inventory lists registered models and readiness rather than providing a schema browser or migration-history viewer. Use the appropriate CLI reference when the page names unavailable data or a supported next step.

See [Projects](configuration.md), [Execution instructions](execution-instructions.md), and [Team collaboration](access.collaboration.md).
