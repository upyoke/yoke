# Scoped-QA dispatch and member close-out

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Deployments](index.md) > QA dispatch
<!-- /yoke:breadcrumbs -->

A scoped-QA stage gates every member and wakes waiting members before closing
accepted members. Each dispatch attempts at most two close-outs and stops
starting more work after five seconds. A close-out already running finishes;
the budget cannot interrupt it. Each member's route is read fresh immediately
before acting, so an earlier close-out cannot leave later routes stale.

Remaining work holds the stage with `qa_member_close_out_pending`. The next
dispatch continues it; acceptance stays recorded, and completed members are
skipped. A refused close-out still wakes its owner with the existing refusal
and recovery.

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
