# Operations and troubleshooting

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Operations and troubleshooting
<!-- /yoke:breadcrumbs -->

Yoke helps your agents find and fix problems. Doctor checks project health, while events, logs, and performance diagnostics help explain failures and slow operations. Agents can also diagnose connection problems and recover Yoke's background services.

Ouroboros, Yoke's learning loop, lets agents record problems as field notes, identify recurring issues, and turn those findings into improvements.

## Doctor

### Health checks and results

Doctor checks the parts of Yoke relevant to the current project, machine, and session. Checks cover areas such as setup, backlog consistency, GitHub integration, worktrees, guidance, and dispatch.

Results distinguish pass, warning, failure, and not applicable. An incomplete check or unavailable read is not a pass. Read the finding's reason and recovery before assuming which component is broken.

Your agent can run a focused check for the reported problem rather than repeating the entire roster. Session readiness checks focus on the session being used; other checks may apply to the machine or selected project. [Doctor reference](../operations/doctor.md)

### Project-specific checks

Projects can add checks under `.yoke/doctor/`. A check declares the runtime, project scope, and capabilities it needs. This lets a project check its own requirements without making them requirements for every Yoke installation.

### Supported repairs

Doctor can apply supported repairs when requested with the appropriate repair option. A repair result should be checked against the original finding. Some problems need a configuration choice, external service repair, or code change rather than an automatic fix.

## Events and logs

### Events and attribution

Events record observed activity with the available project, session, actor, and operation context. Use that attribution to connect a reported failure to the work or service involved.

Event history is diagnostic. An absent event does not establish that nothing happened, and an event does not replace the durable item, run, claim, or decision record that owns current state. [Events reference](../operations/events.md)

### Log capture and watchers

Watchers follow long-running operations and report progress or completion. When a command returns a capture or diagnostic reference, use it to inspect the relevant output rather than rerunning the operation just to recover its logs.

Relay logs and some command captures remain on the machine that produced them. Your agent can request supported evidence through the owning session and machine. [Machine-local evidence](../databases/machine-local-evidence.md)

## Performance diagnostics

### Operation timing and slow operations

The Performance dashboard shows retained observations for the selected Universe and projects. Use the time range and filters to find slow functions, tools, hooks, relay waits, or watchers.

Different measurements cover different intervals. A function's handler time does not include every part of a browser request, and a watcher deliberately waiting for work is not equivalent to a slow ordinary command.

### Diagnostic evidence

Inspect contributing observations before assigning a cause. Missing timings, gaps, and expired history remain unknown rather than appearing as zero latency. A useful performance report names the operation, scope, time window, and observed duration. [Performance diagnostics](../operations/performance-diagnostics.md)

## Connections and services

### Connection selection and authentication

First confirm which Universe and connection the command is using. A valid credential for another Universe does not resolve access to the intended one. Authentication failures, missing permissions, and unreachable endpoints need different recovery steps.

For HTTPS failures, inspect the named cause: certificate validity, hostname, trust chain, DNS, network reachability, or server availability. Preserve certificate verification while correcting the configuration. A timeout after sending a write can leave its outcome unknown, so inspect the affected record before repeating the change. [Connection diagnostics](../cli/https-connection-diagnostics.md)

### Local PostgreSQL and Yoke core

Local hosting includes services that must be running for the Universe to answer. Diagnose the selected connection and service state before restarting or replacing anything. Service recovery should preserve the database and existing work.

Self-hosted deployments have their own server and network responsibilities. See [Self-hosting](self-hosting.md) for administration and [local connection repair](../verification/local-connection-repair.md) for the supported recovery path.

### Relay diagnostics and recovery

The relay connects a machine's execution capabilities to Yoke. A healthy control plane does not prove that every machine's relay is reachable or that its harness can launch.

Inspect the affected machine, relay, and session evidence. Recover the component identified by that evidence, then recheck readiness. See [Yoke CLI and relay](cli-relay.md).

## Universe retention

### Retention policies and protected records

Retention governs eligible disposable records in the connected Universe. Age alone does not make every record removable: live references, unresolved work, human messages, and durable work history have protection rules.

The retention read shows the effective policy. A Universe administrator should review that policy and the intended connection before pruning. There is no general dashboard retention editor implied by this feature.

### Previewing and applying pruning

Pruning defaults to a preview. It reports eligible records and protected records without deleting them. Applying pruning requires the authorized administrator to select the apply mode; it works in bounded transactions and preserves committed progress if interrupted.

Retention is not a backup strategy. See [Universe portability, backup, and restore](universe-portability.md) for that separate responsibility and [retention reference](../universe-retention.md) for exact protections and commands.

## Ouroboros

### Field notes

A field note records a problem, missing guidance, or observation with evidence. It should explain what failed and what the system should have handled. Routine progress belongs in the item's Progress Log.

### Repeated observations

Correlate a repeat with the original note so the learning queue reflects recurring causes rather than a collection of disconnected reports. Keep each occurrence's evidence available.

### Curation and follow-up work

Curation reviews the notes, checks whether causes are already addressed, and groups unresolved findings into useful follow-up work. It records handled findings and retains the relationship to the work that fixes them.

Recording a note does not itself fix the problem. The learning loop becomes useful when findings produce changes to guidance, configuration, or software and those changes are verified. [Ouroboros reference](../operations/ouroboros.md)
