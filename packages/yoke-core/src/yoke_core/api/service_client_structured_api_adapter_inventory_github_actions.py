"""GitHub Actions entries for the structured API adapter inventory."""

from __future__ import annotations

from typing import Tuple

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


GITHUB_ACTIONS_ADAPTERS: Tuple[AdapterEntry, ...] = (
    _read_entry(
        function_id="github_actions.dispatch_receipt.get",
        cli_invocation=(
            "yoke github-actions dispatch-receipt get REQUEST-ID --project P [--session-id S] [--json]"
        ),
        notes="Read the durable original inputs and run identity in the authorized project; absent requests return found=false. Rejoin with the original payload.",
    ),
    AdapterEntry(
        function_id="github_actions.run.cancel",
        cli_invocation=(
            "yoke github-actions run cancel REPO RUN-ID --project P [--session-id S] [--json]"
        ),
        notes="Ordinary cancellation of one run in the project's bound repository; its cancelled() steps still run, and a finished run answers already_completed.",
    ),
    AdapterEntry(
        function_id="github_actions.run.rerun_failed",
        cli_invocation=(
            "yoke github-actions run rerun-failed ITEM RUN-ID "
            "[--session-id S] [--json] [--project P]"
        ),
        notes="Claimed-item CI recovery: current PR head and newest workflow run only; intent and outcome persist in the item Progress Log.",
    ),
    AdapterEntry(
        function_id="github_actions.workflow.dispatch",
        cli_invocation=(
            "yoke github-actions workflow dispatch <repo-slug> <workflow-file> [--ref REF] [--input KEY=VALUE] --request-id ID --correlation-input yoke_dispatch_id --project P [--session-id S] [--json]"
        ),
        notes=(
            "Exact-id workflow_dispatch through hosted GitHub App authority; "
            "the GitHub POST is intentionally not retried."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.workflow.dispatch_once",
        cli_invocation=(
            "yoke github-actions workflow dispatch-once <repo-slug> <workflow-file> [--ref REF] [--input KEY=VALUE] --project P [--session-id S] [--json]"
        ),
        notes=(
            "Explicit one-shot workflow_dispatch for correlation-unaware "
            "rollout compatibility; response loss is never retried."
        ),
    ),
    _read_entry(
        function_id="github.branch.head",
        cli_invocation=(
            "yoke github branch head <branch> [--since SHA] --project P [--session-id S] [--json]"
        ),
        notes=(
            "Reads the bound repository's branch head through the project's "
            "GitHub binding; --since adds identical / descendant / "
            "not_descendant ancestry."
        ),
    ),
    _read_entry(
        function_id="github.open_work.list",
        cli_invocation=(
            "yoke github open-work list --project P [--limit N] [--full] [--session-id S] [--json]"
        ),
        notes=(
            "Lists the bound repository's open issues and open pull requests, "
            "newest-updated first, through the project's GitHub binding."
        ),
    ),
    _read_entry(
        function_id="github_actions.commit_runs.list",
        cli_invocation=(
            "yoke github-actions commit-runs list <commit-sha> [--workflow NAME] [--repo owner/name] --project P [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="github_actions.workflow.find_run",
        cli_invocation=(
            "yoke github-actions workflow find-run <repo-slug> <workflow-file> [<commit-sha>] [--branch BRANCH] [--event EVENT] [--status STATUS] --project P [--session-id S] [--json]"
        ),
        notes=(
            "Commit SHA and/or --branch; result.head_sha is the matched "
            "run's own commit, not a branch tip. Trunk resolution for a "
            "consumer-project input binding lives in the deploy pipeline's "
            "own driver (deploy_pipeline_github_workflow_bindings), via a "
            "plain git ls-remote against the project's registered "
            "checkout, not this call. Wrong guess: keying reuse on "
            "floating main or GITHUB_RUN_ATTEMPT."
        ),
    ),
    _read_entry(
        function_id="github_actions.run.jobs_count",
        cli_invocation=(
            "yoke github-actions run jobs-count <repo-slug> <run-id> [--attempt N] --project P [--session-id S] [--json]"
        ),
        notes="Point-in-time workflow-run attempt job count.",
    ),
    _read_entry(
        function_id="github_actions.check_ci",
        cli_invocation=(
            "yoke github-actions check-ci <repo-slug> <workflow-file> [--branch BRANCH] [--head-sha SHA] [--wait] [--timeout SEC] --project P [--session-id S] [--json]"
        ),
        notes=(
            "bearer-token branch and exact-commit CI gate via "
            "gh_rest_transport; "
            "single-shot handler. --wait/--timeout poll CLIENT-side in "
            "the adapter, one dispatch per poll."
        ),
    ),
    _read_entry(
        function_id="github_actions.failed_log",
        cli_invocation=(
            "yoke github-actions failed-log <repo-slug> [<run-id>] [--workflow WORKFLOW] [--branch BRANCH] [--head-sha REF] [--lines N] [--full] --project P [--session-id S] [--json]"
        ),
        notes=(
            "Reports EVERY failed job of the run, each read by job id as "
            "soon as it finishes (siblings may still be running) — each "
            "matrix shard in its own labelled block with job id, GitHub "
            "job URL, and its failure region bounded by --lines; --full "
            "writes each complete log to a local file. A job whose log is "
            "unavailable is named with the reason. Omit the run id and "
            "pass --workflow with optional --head-sha to resolve from the "
            "current checkout."
        ),
    ),
    _read_entry(
        function_id="github_actions.wait_run",
        cli_invocation=(
            "yoke github-actions wait-run <repo-slug> <run-id> [--timeout SEC] [--receipt-artifact-prefix PREFIX] --project P [--session-id S] [--json]"
        ),
        notes=(
            "bearer-token workflow-run polling wrapper. The registered "
            "server read is single-shot; wait/timeout stays client-side."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.runners.status",
        cli_invocation=(
            "YOKE_ENV=prod-db-admin yoke github-actions runners status "
            "<owner/repo> --required-label self-hosted --required-label "
            "Linux --required-label ARM64 --required-label "
            "yoke-github-actions --project <project>"
        ),
        notes=(
            "Read-only repo self-hosted-runner status plus capability "
            "routing_enabled and Pulumi-owned YOKE_LINUX_RUNS_ON drift "
            "probe via gh_rest_transport; source-dev/admin CI-capacity "
            "setup surface."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.secret.set",
        cli_invocation=(
            "yoke github-actions secret set <repo-slug> <secret-name> [VALUE | --value-file PATH | --value-stdin] --project P [--session-id S] [--json]"
        ),
        notes=(
            "Sealed-box repo-secret create-or-update via "
            "github_secrets_rest; direct VALUE is the default."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.secret.delete",
        cli_invocation=(
            "yoke github-actions secret delete <repo-slug> <secret-name> --project P [--session-id S] [--json]"
        ),
        notes="Audited post-window repo-secret retirement through bound GitHub App authority.",
    ),
    AdapterEntry(
        function_id="github_actions.dispatch_tag.ensure",
        cli_invocation=(
            "yoke github-actions dispatch-tag ensure <repo-slug> <tag> <commit-sha> --project P [--session-id S] [--json]"
        ),
        notes=(
            "Create-only lightweight dispatch tag for a stage declaring "
            "run_from_release_commit; refuses a conflicting existing tag."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.variable.get",
        cli_invocation=(
            "yoke github-actions variable get <repo-slug> <variable-name> --project P [--session-id S] [--json]"
        ),
        notes=(
            "Read-only repo-variable probe via github_variables_rest; "
            "exists=false when absent."
        ),
    ),
    AdapterEntry(
        function_id="github_actions.variable.set",
        cli_invocation=(
            "yoke github-actions variable set <repo-slug> <variable-name> --value VALUE --project P [--session-id S] [--json]"
        ),
        notes="bearer-token repo-variable upsert via github_variables_rest.",
    ),
    AdapterEntry(
        function_id="github_actions.variable.delete",
        cli_invocation=(
            "yoke github-actions variable delete <repo-slug> <variable-name> --project P [--session-id S] [--json]"
        ),
        notes="Audited post-window repo-variable retirement through bound GitHub App authority.",
    ),
    AdapterEntry(
        function_id="github.merge_queue.apply",
        cli_invocation=(
            "yoke github merge-queue apply --project P [--declaration PATH] [--preview] [--session-id S] [--json]"
        ),
        notes=(
            "Idempotently apply .yoke/merge-queue.json (ruleset + "
            "allow_auto_merge); requires Administration: write."
        ),
    ),
    AdapterEntry(
        function_id="github.merge_queue.hold",
        cli_invocation=(
            "yoke github merge-queue hold ITEM [--project P] [--session-id S] [--json]"
        ),
        notes=(
            "Clear merge-when-ready AND remove the queue entry, then verify "
            "both from a readback; never re-arms."
        ),
    ),
    _read_entry(
        function_id="github.merge_queue.readiness",
        cli_invocation=(
            "yoke github merge-queue readiness ITEM [--project P] "
            "[--json] [--session-id S]"
        ),
        notes=(
            "Read-only landing liveness from the pull request plus the named "
            "mergeQueue(branch).entries state; consumed arming is not cleared."
        ),
    ),
)


__all__ = ["GITHUB_ACTIONS_ADAPTERS"]
