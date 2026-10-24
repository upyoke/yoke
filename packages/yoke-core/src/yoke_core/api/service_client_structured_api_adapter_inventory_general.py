"""Adapter inventory rows for single ``yoke`` commands outside a larger family.

Each row records the command's ``yoke ...`` usage, which must match the CLI's
own usage line. read_shape mirrors each handler's declared side-effects
(reads have none).
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

GENERAL_ADAPTERS: List[AdapterEntry] = [
    AdapterEntry(
        "db_claim.prose_check",
        (
            "yoke db-claim prose-check (<PREFIX-N> | --stdin) [--public-ref PREFIX-N] [--project P] [--full] [--session-id S] [--json]"
        ),
        notes="prose-vs-claim; --stdin local",
    ),
    AdapterEntry(
        function_id="lifecycle.transition.execute",
        cli_invocation=(
            "yoke lifecycle transition <PREFIX-N> --to STATUS [--from STATUS] [--reason TEXT] [--project P] [--session-id S] [--json]"
        ),
        notes=(
            "Lifecycle status transitions ride on items.scalar.update; the "
            "engine evaluates every listed and structural gate of the pinned "
            "definition on the write."
        ),
    ),
    AdapterEntry(
        function_id="lifecycle.repair_status.execute",
        cli_invocation=(
            "yoke lifecycle repair-status <PREFIX-N> --to STATUS "
            "--reason TEXT [--from STATUS] [--dry-run] [--session-id S] "
            "[--json] [--project P]"
        ),
        notes="steering-seat audited lifecycle reconciliation",
    ),
    AdapterEntry(
        "lifecycle.skip.record_recoverable_substrate",
        (
            "yoke lifecycle skip record-recoverable-substrate <PREFIX-N> --chain-step N --project P --routed-action ACTION --failure-class CLASS --remediation-owner OWNER [--current-status STATUS] [--useful-work-began] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "actors.state.set",
        (
            "yoke actors state set ACTOR-ID (--enable | --disable) [--confirm-system-retirement] [--session-id S] [--json]"
        ),
        notes="org-admin actor lifecycle; system retirement requires explicit dependency attestation",
    ),
    AdapterEntry(
        "actors.role.set",
        (
            "yoke actors role set (ACTOR-ID | --member EMAIL) --role ROLE [--session-id S] [--json]"
        ),
        notes="org-admin; sets a person's one org role",
    ),
    AdapterEntry(
        "machine.register",
        (
            "yoke machine register [--name NAME] [--access-mode owner_only|actors|project_role|universe] [--session-id S] [--json]"
        ),
        notes="registers this host and rotates its machine-bound bearer",
    ),
    AdapterEntry(
        "machine.retire",
        ("yoke machine retire [MACHINE-ID] --confirm [--session-id S] [--json]"),
        notes="preserves history and revokes only the machine-bound bearer",
    ),
    AdapterEntry(
        "machine.access.set",
        (
            "yoke machine access set [MACHINE-ID] --path use.mode --value '\"universe\"' [--session-id S] [--json]"
        ),
        notes="owner or administrator edits one leaf of the access document",
    ),
    _read_entry(
        function_id="machine.list",
        cli_invocation=("yoke machine list [--mine] [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="machine.show",
        cli_invocation=("yoke machine show [MACHINE-ID] [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="machine.detail",
        cli_invocation=("yoke machine detail [MACHINE-ID] [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="machine.access.get",
        cli_invocation=(
            "yoke machine access get [MACHINE-ID] [--path use.mode] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="events.tail.run",
        cli_invocation=(
            "yoke events tail [--limit N] [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="events.count.run",
        cli_invocation=(
            "yoke events count [--event-name NAME] [--item PREFIX-N] [--project P] [--session S] [--source-type T] [--event-kind K] [--agent A] [--service SVC] [--actor-id N] [--trace-id T] [--tool-use-id ID] [--turn-id ID] [--hook-event-name NAME] [--min-severity LEVEL] [--since WHEN] [--until WHEN] [--current-episode] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="events.anomalies.run",
        cli_invocation=(
            "yoke events anomalies [--event-name NAME] [--item PREFIX-N] [--project P] [--session S] [--source-type T] [--event-kind K] [--agent A] [--service SVC] [--actor-id N] [--trace-id T] [--tool-use-id ID] [--turn-id ID] [--hook-event-name NAME] [--min-severity LEVEL] [--since WHEN] [--until WHEN] [--current-episode] [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="claims.path.list",
        cli_invocation=(
            "yoke claims path list --item PREFIX-N [--state S]... [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="claims.path.get",
        cli_invocation=(
            "yoke claims path get CLAIM_ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="ouroboros.entry.list",
        cli_invocation=(
            "yoke ouroboros entry list [--unreviewed] [--project P] [--limit N] [--offset N] [--count] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="ouroboros.entry.get",
        cli_invocation=(
            "yoke ouroboros entry get ENTRY-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="ouroboros.field_note.list",
        cli_invocation=(
            "yoke ouroboros field-note list [--unreviewed] [--project P] [--limit N] [--offset N] [--count] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="ouroboros.field_note.get",
        cli_invocation=(
            "yoke ouroboros field-note get ENTRY_ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="projects.list",
        cli_invocation=(
            "yoke projects list [--include-retired] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="identity.link.set",
        cli_invocation=(
            "yoke identity link set --actor ACTOR (--issuer I --subject "
            "S [--email E] | --email E) [--org ORG] [--json] "
            "[--session-id S]"
        ),
        notes="issuer+subject links directly; --email alone pre-links a future sign-in",
    ),
    _read_entry(
        function_id="items.list.run",
        cli_invocation=(
            'yoke items list [--status STATUS] [--priority PRIORITY] [--workflow W] [--frozen 0|1] [--blocked 0|1] [--project P|all] [--fields "f1,f2,..."] [--limit N] [--full] [--session-id S] [--json]'
        ),
    ),
    _read_entry(
        function_id="items.search.run",
        cli_invocation=(
            "yoke items search KEYWORDS [--project P|all] [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="db.read.run",
        cli_invocation=(
            'yoke db read "SELECT ..." [--format human|json|lines] [--full] [--session-id S] [--json]'
        ),
    ),
    _read_entry(
        function_id="items.dependency.list",
        cli_invocation=(
            "yoke items dependency list (PREFIX-N | --item PREFIX-N) [--full] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="shepherd.verdict.run",
        cli_invocation=(
            "yoke shepherd verdict --item PREFIX-N --transition T --worker W --verdict V [--caveats TEXT] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="shepherd.caveat_disposition.run",
        cli_invocation=(
            "yoke shepherd caveat-disposition --item PREFIX-N --transition T --attempt N --caveat-num N --caveat-text TEXT --disposition RESOLVED|DEFERRED|ANALYZED [--resolution-details TEXT] [--verdict-id N] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="github.release.create_commit_tag",
        cli_invocation=(
            "yoke github release create-commit-tag <repo-slug> <source-sha> --summary TEXT --project P [--session-id S] [--json]"
        ),
        notes="Immutable commit UTC clock tag with a declared serving floor.",
    ),
    AdapterEntry(
        function_id="github.pr.create",
        cli_invocation=(
            "yoke github pr create --title TITLE --head BRANCH [--base BRANCH] [--body TEXT | --body-stdin] [--draft] --project P [--session-id S] [--json]"
        ),
        notes="bearer-token PR create; repo resolves from project capability.",
    ),
    _read_entry(
        function_id="doctor.last_run.get",
        cli_invocation=(
            "yoke doctor last-run get [--project NAME] [--full] [--session-id S] [--json]"
        ),
        notes=(
            "Reads the newest completed doctor run from doctor_runs; "
            "the events journal is telemetry only."
        ),
    ),
    AdapterEntry(
        function_id="board.rebuild.run",
        cli_invocation=(
            "yoke board rebuild [--force] [--repo-root PATH] [--output-name NAME] [--scope NAME] [--print | --print-only] [--no-pager] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="board.data.get",
        cli_invocation=(
            "yoke board data get [--scope NAME] [--full] [--session-id S] [--json]"
        ),
        notes=(
            "Server half of the board rebuild composition: returns the "
            "recorded query plan; rendering and file writes stay client-side."
        ),
    ),
    _read_entry(
        function_id="lint.config.show",
        cli_invocation=(
            "yoke lint config show [--root PATH] [--session-id S] [--json]"
        ),
        notes=(
            "Reports the resolved .yoke/lint-config, how its root was chosen, "
            "and each guard's effective mode, including a protected-guard warn "
            "clamped back to deny for a missing allow-warn token."
        ),
    ),
    AdapterEntry(
        function_id="hook.evaluate.run",
        cli_invocation="yoke hook evaluate <event> [--dry-run]",
    ),
    _read_entry(
        function_id="scratch.dispatch_inputs",
        cli_invocation=(
            "yoke scratch dispatch-inputs PREFIX-N SESSION-ID ATTEMPT [--project P] [--full]"
        ),
        notes="Helper-resolved dispatch-inputs path; wraps yoke_cli.commands.adapters.misc.scratch_dispatch_inputs.",
    ),
]

__all__ = ["GENERAL_ADAPTERS"]
