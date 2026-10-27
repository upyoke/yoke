# Command and technical reference

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > Command and technical reference
<!-- /yoke:breadcrumbs -->

Use the guide pages to understand Yoke's concepts and the reference pages for precise commands, fields, and operating rules. Your agent receives relevant guidance through help, command responses, context packets, and installed instructions; you can inspect the same detail when you need it.

## Function contracts

### Functions and CLI commands

Yoke operations have registered function contracts. The CLI exposes those operations as commands, while the contract defines their inputs, authorization, effects, and results. A command's help is the place to check its supported arguments and recovery steps.

Start with `yoke --help`, then narrow to a command group and action. Reading help does not perform the action. Routine reads return summaries; use the fields, filters, pages, or full-read option the command offers when you need more detail.

[CLI reference](../../cli/index.md) · [Help and replies](../../cli/help.md) · [Function families](../../functions/index.md)

### Contract families

| Subject | Detailed reference |
|---|---|
| Work items | [Items](../../functions/items.md) |
| Workflows and transitions | [Workflows](../../functions/workflows.md) |
| Claims | [Claims](../../functions/claims.md) |
| Worktrees | [Worktrees](../../functions/worktrees.md) |
| Generated tasks | [Tasks](../../functions/tasks.md) |
| Project configuration | [Project configuration](../../functions/project-configuration.md) |
| QA | [QA](../../functions/qa.md) |
| Runtime | [Runtime](../../functions/runtime.md) |
| Models | [Models](../../functions/models.md) |
| Merge-queue attempts | [Landing attempts](../../functions/merge-queue-landing-attempts.md) |

### Inputs and results

Use the public identifiers and shapes the command returns. A refusal describes a condition that prevented the operation, not a successful empty result. Read the reason and supported recovery instead of guessing alternate writes.

Machine-readable output preserves structured results. Human output emphasizes the current question and can link to deeper reads. Neither a local cache nor a rendered document replaces the record that owns the fact.

## Agent operation rules

### Rules by operation

Operation homes explain how agents carry out classes of work: code changes, shell calls, item updates, claims, verification, delivery, databases, Packs, and architecture changes. The agent should read the relevant home before acting rather than load every procedure at once.

[Operation-home index](../../agents/rules/index.md)

### Shared and project-specific authority

Public operation homes contain reusable product procedures. Project-specific constraints belong in project guidance and [Execution instructions](../execution-instructions.md). A particular installation's credentials, topology, or release policy should not become a requirement for every user.

The [Agent guidance](../guidance.md) page explains how installed files, skills, packets, and command feedback reach the agent. Detailed rules remain accessible to humans without making the introductory guide repeat them all.

## Time and runtime contracts

### Timestamp encoding

Time fields need unambiguous encoding so records from different machines can be compared correctly. Runtime contracts define accepted timestamps and conversion rules; user interfaces can display local time without changing the stored instant.

[Timestamp encoding](../../runtime/time/encoding.md)

### Clock verification

Verification distinguishes an observed timestamp from a guessed one and defines how time-sensitive behavior is checked. This matters for claims, leases, retries, and evidence ordering.

[Time verification](../../runtime/time/verification.md)

### Writer ownership

Each runtime fact has an owning writer and contract. Other components should consume that record rather than create competing versions of the same truth. Follow the ownership reference when extending a runtime integration.

[Runtime overview](../../runtime/index.md) · [Time ownership](../../runtime/time/ownership.md) · [Integration ownership](../../runtime/time/ownership-integrations.md)

## Documentation contracts

### Human summaries and detailed homes

Each guide page explains the subject in plain language and links to the detailed contracts. Details belong with the operation or concept that owns them, so a correction has one maintained home.

### Navigation and links

Links should identify the destination clearly and keep detailed reference reachable from the relevant human page. Existing reference links remain useful for agents, advanced readers, and installed guidance.

### Published and installed copies

Public documentation is authored in the Yoke repository and distributed through the website and installed documentation bundle. Installed guidance should match the release in use. A source-contributor procedure is not automatically an installed user's requirement.

[Teaching standard](../../documentation/index.md) · [Navigation contract](../../documentation/navigation.md) · [Documentation verification](../../documentation/verification.md)

<!-- yoke:contents -->
- [Installation reference](../../start/index.md) — Detailed installation commands, supported platforms, and recovery.
- [Agents](../../agents/index.md) — Use harness guidance, command maps and operation homes before acting.
- [Projects](../../projects/index.md) — Add projects and configure their capabilities, guidance and shared files.
- [GitHub](../../github/index.md) — Connect repository access, mirror issues and inspect merge evidence.
- [CLI and config](../../cli/index.md) — Read command help, choose connections and configure your machine.
- [Items](../../items/index.md) — Read and update backlog work, generated tasks and landing evidence.
- [Sessions](../../sessions/index.md) — Inspect live sessions, ownership, messages and steering reports.
- [Workflows](../../workflows/index.md) — Choose definitions and follow pinned lifecycle gates and transitions.
- [Strategy](../../strategy/index.md) — Maintain project direction and select ready work from the frontier.
- [Deployments](../../deployments/index.md) — Follow delivery destinations, inspect runs and read release authority.
- [Databases](../../databases/index.md) — Inspect declared models, migration conventions and governed repair.
- [Functions](../../functions/index.md) — Discover typed function envelopes and registered operation families.
- [Verification](../../verification/index.md) — Define cases, execute project plans and inspect evidence for workflow gates.
- [Operations](../../operations/index.md) — Inspect events, run health checks, record learning and diagnose performance.
- [Runtime](../../runtime/index.md) — Encode native instants, verify clocks and find timestamp ownership boundaries.
- [Documentation](../../documentation/index.md) — Write, navigate and verify complete, concise teaching.
<!-- /yoke:contents -->
