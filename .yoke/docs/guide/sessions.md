# Steering and fleet control

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Steering and fleet control
<!-- /yoke:breadcrumbs -->

Your coding agent uses Yoke to take a STEERING seat claim for one or more projects and working strategy docs. It files work items, staffs them on an available harness on your machine or another connected machine, and orchestrates delivery while you guide the work and make key decisions.

STEERING uses Yoke to launch parallel CLI sessions across available machines and coding harnesses. Fleet messaging lets it communicate with those sessions and coordinate execution and delivery.

<!-- yoke:visual fleet -->

## Steer and coordinate work

### Who coordinates which scope

A steering seat records responsibility for a scope of work. A project-wide seat covers the project; a document-scoped seat covers items linked to that working strategy document. Document locks keep two coordinators from independently rewriting the same standing plan.

A steering seat differs from a work claim. Steering coordinates the work; a work claim identifies the session doing a particular item. The dashboard shows these roles so a team can see who is responsible without reconstructing separate chats.

### Standing plans and work selection

The working strategy doc holds direction and the rolling plan. Filed work enters the Frontier, where dependencies, workflow requirements, priority, and ownership determine what can advance. Steering staffs eligible work and follows it through the required steps.

Steering is not a promise that every machine can run every harness. A launch needs a connected relay, an available supported harness, the required sign-in, and suitable capacity. See [Yoke CLI and relay](cli-relay.md).

### Reading waits and decisions

A waiting item may need a dependency, QA result, release, human decision, or available capacity. The steering report brings these facts together so the coordinating agent can act on the cause rather than repeatedly trying to start blocked work.

A parked session can keep a valid work claim during a wait. That is deliberate ownership, not evidence that the item has been abandoned.

### Resolving contention

Work and path claims identify existing owners. When work overlaps, agents coordinate or record the relevant dependency instead of silently taking each other's files. Explicit release, completion, cancellation, or authorized termination changes ownership; inactivity alone does not make protected work free.

See the [session reference](../sessions/index.md) and [steering report](../sessions/steering-report.md).

## Messages and human decisions

### Messages versus decisions

Fleet messages carry instructions, questions, blockers, and results between sessions. A message receipt records delivery or acknowledgement, not agreement to perform the requested work.

A decision is a separate request whose answer satisfies a configured requirement. Your agent can bring decisions to you in conversation, and **Inbox** shows pending approvals with their evidence and effects.

### Delivery and queued messages

A running session can receive messages through its hooks. A parked or idle session may require you to open the chat and start its next turn; its card explains that delivery is queued. Relay-supported wakes and operator-driven delivery are distinct paths.

If delivery fails, inspect the recorded reason and recovery. A queued message is not proof that the recipient acted, and an acknowledgement is not proof that the work finished.

### Human approval and follow-up

Review the subject and evidence before approving. Different decisions can concern an item's work, QA evidence, or a deployment run. Answering one does not settle the others.

See [Inbox and messaging](../sessions/inbox.md) and [Team collaboration](access.collaboration.md).

## Levels and staffing

### What levels mean

Execution levels group model and minimum-effort choices for staffing. They let a workflow ask for an appropriate level without hard-coding a single model into every stage. They are unrelated to the Git worktrees that isolate code changes.

### Models and effort

A session's model and effort determine which configured level it matches. Levels can provide multiple model choices, and workflow stages can have defaults. The available choices come from the current model and harness configuration rather than a permanent list in this guide.

### Who assigns work

Steering or explicit operator staffing chooses what a worker does. A session's level does not itself claim work. The workflow binding determines the skill used for the current segment, while ownership and readiness still govern whether execution can proceed.

### Capacity and recovery

Launch limits and available harness capacity can delay staffing. Yoke records queued launches and the reasons they wait. Your agent can inspect those facts, choose an eligible placement, or follow the named recovery when a relay or harness fails.

See [Execution levels](../agents/levels.md), [Level launches](../agents/level-launches.md), and [Capacity recovery](../agents/capacity-recovery.md).

## Sessions

### Harness sessions and work ownership

A harness session is a coding-agent conversation registered with Yoke. It retains its identity, work claims, and coordination records across turns. A session starts in a project or outside projects and may work on accessible items according to its permissions.

A browser sign-in session is different: it establishes dashboard access and is not a coding worker.

### Registration and heartbeat

Harness hooks register sessions and report activity. The relay supplies machine and process information. Session liveness, current turn activity, and item state are separate facts; an old activity timestamp does not by itself mean work is abandoned.

### Parking and resuming

Parking records an intentional pause. A session holding work can remain waiting while preserving its claims, then resume with the item's records and strategy context. End or release ownership explicitly when handing the work elsewhere.

### Relay failure and recovery

A disconnected relay can prevent new launches or automatic wakes while server records remain intact. Check the affected machine and the reported diagnostic before restarting services or terminating a session. See [Operations and troubleshooting](operations.md) and [Linux relay supervision](../sessions/linux-relay.md).
