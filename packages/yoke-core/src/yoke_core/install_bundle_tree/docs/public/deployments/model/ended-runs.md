# Ended deployment runs

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Ended runs
<!-- /yoke:breadcrumbs -->

Read what happens to the GitHub workflows a deployment run dispatched once the run ends.

## Ending a run cancels its workflows

When a run ends `failed` or `cancelled` — operator terminalization, a failed stage's status write, a rejected stage approval, or takeover by a newer run — every GitHub workflow it dispatched through a correlated dispatch intent (`github_workflow_dispatch_intents` rows whose `request_id` starts `deploy:<project>:<run>:`) is asked to cancel, newest attempt per stage, strictly after the close commits (`deployment_run_workflow_cancellation`). The cancellation is ordinary, so each workflow's `if: cancelled()` steps still run and can release what it started. A miss never reopens the run: `yoke deployment-runs terminalize` prints each outcome (`cancel_requested`, `already_completed`, `run_unidentified` with the correlation id to find it by, or `cancel_failed` with its recovery `yoke github-actions run cancel REPO RUN-ID --project P`), and every path logs misses with the same recovery. A one-shot dispatch records no intent, so it is not cancelled here.

## Related

- [Runs](runs.md)
- [Run members and QA](run-members.md)
