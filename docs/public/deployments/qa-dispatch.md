# Scoped-QA dispatch and member close-out

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > QA dispatch
<!-- /yoke:breadcrumbs -->

A scoped-QA stage gates every member and wakes waiting members before closing
accepted members. A member held by a QA configuration refusal
(`qa_configuration_refused`) is woken too, once per wait, with the refusal and
its recovery.

Each dispatch closes accepted members in order and stops starting more work
after five seconds. A close-out already running finishes; the budget cannot
interrupt it. Each member's route is read fresh immediately before acting, so
an earlier close-out cannot leave later routes stale. A refused close-out
wakes its owner with the refusal and recovery, and the next member is still
tried. The refused member retries by itself when its blocking record settles.
A member the budget skipped closes on a later dispatch or at settlement; the
skip never holds the stage.

If the idempotent dispatch exceeds its HTTPS response limit, the client waits
for the server's existing reservation and recorded result using the identical
request envelope and request id. It makes up to ten 60-second HTTPS waits,
each within the hosted response cap. It never recovers this timeout through
the self-deploy database door. The server replays a completed successful call;
QA dispatch is also safe to repeat if the original failed before recording a
successful result.

An unanswered recovery reports `qa_dispatch_result_unconfirmed`, leaving the
run resumable at its QA stage. Read `yoke deployment-runs get RUN-ID` and the
driver capture before re-driving that same run. Do not use `--fresh` or the
database door to recover an unknown result.

See [deployment start diagnostics](start-diagnostics.md) for other lost
responses, stage interruptions and bounded QA waits.
