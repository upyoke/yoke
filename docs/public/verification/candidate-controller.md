# Candidate controller

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Candidate controller
<!-- /yoke:breadcrumbs -->

Controller-side work (Machine host control, mission preparation and the
walker's mission commands) runs the release's own Yoke code, not the CLI
installed on the controller machine. After begin, before any host lease, a
release-run execution whose target names an installer origin compares this
controller's build commit with the candidate: the run's `release_lineage`
served on the target's channel, or the release its deployed commit pins.
A stale controller installs the candidate's published wheels into a private
runtime under `~/.yoke/qa-controller-runtimes/` and hands it the begun
execution; the installed CLI and its channel are never changed. The walker's
review bundle names that runtime's `yoke`; run those commands exactly as shown.

When the target's channel serves another build than the target's
`release_lineage` (after a takeover, the owning run's once it has a ready
deploy receipt), the refusal names the run and build from that target, and
the run that now owns the execution when a takeover moved it. Before giving
the execution up, the command begins it again in place up to three times,
20 seconds apart: an execution that has run nothing takes its owning run's
current target and keeps its queue place. Only a target that stays stale
releases the execution.

When the runtime cannot be provisioned, the command refuses
`qa_controller_not_candidate` with the installed and candidate versions,
aborts the unused execution and names the recovery. Machine case and mission
preparation evidence record `controller_runtime` with the build's
`source_commit`.

## Related

- [Deployment plan execution](deployment-plan-execution.md)
- [Deployment QA continuity](deployment-qa-continuity.md)
