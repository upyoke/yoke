"""Project-capability packet table entry."""

from __future__ import annotations


PROJECT_CAPABILITIES_TABLE: dict[str, object] = {
    "columns": [
        ("id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("type", "TEXT"),
        ("verified_at", "TEXT"),
        ("created_at", "TEXT"),
        ("settings", "TEXT"),
    ],
    "notes": (
        "Project capability rows keyed by `(project_id, type)`. The "
        "same commands and capability resolution apply to every project "
        "slug; every registered project is an ordinary project row, and "
        "specialized behavior comes from capabilities, environments, and "
        "workflow definitions rather than project-name checks. The "
        "capability-name column is `type` (values include "
        "`github`, `docker`, `domain`, `migration_model`, and "
        "`github-actions-runner-fleet`); `settings` is a JSON blob carrying "
        "capability-specific configuration. The `github-actions-runner-fleet` "
        "network settings use `deployment_ssh_environments` for active VPS "
        "environment selectors and `deployment_ssh_stack_names` for explicit "
        "standalone VPS Pulumi stack references. The renderer merges and "
        "deduplicates them, binding environment stacks to "
        "`originElasticIpAddress` and standalone VPS stacks to "
        "`vpsElasticIpAddress`; neither output nor a literal address is "
        "guessed from the stack name. Canonical non-sensitive settings access "
        "is `yoke projects capability-settings get --project <slug> --cap-type "
        "<type>`, except that capability listings may include `pulumi-state` "
        "and its aggregate settings read is closed. Declare an exact "
        "`pulumi-state.stacks` entry through the typed capability-settings "
        "merge surface, initialize that declared stack through `yoke pulumi "
        "exec`, and fetch its exact rendered program with `yoke projects "
        "pulumi-stack-config get --project <slug> --stack <name> --output "
        "<owner-only-file>`. Full writes use the exact returned text with "
        "`capability-settings set ... --base <as-read-json>` (or `--new` for "
        "an absent row); single-path repairs use `capability-settings merge "
        "... --set key.path=value`. These registered surfaces work over HTTPS, "
        "protect against lost updates, and run capability-specific typed "
        "canonicalization before mutation. Unknown fields on typed "
        "capabilities are refused so a mixed-version control plane cannot "
        "silently drop new authority fields. GitHub settings remain "
        "binding-owned. `pulumi-state` accepts only known typed keys; its "
        "generic get/full-set/operator-state merges are closed. Aggregate-read "
        "callers must use typed declaration merge, stack initialization, or "
        "exact stack-config fetch according to their intent. Every environment "
        "`pulumi.origin_vps_stack_name` is an exact standalone VPS stack-config "
        "target sourced from that environment's first `servers` entry, not the "
        "renderer primary. Its exact `pulumi-state.stack_state[stack_name]` "
        "entry must provide operator state; missing state refuses rather than "
        "borrowing. For a live stack without legacy site settings, register the "
        "exact checkpoint entry with `yoke projects pulumi-state "
        "checkpoint-import --project <slug> --stack <name> --checkpoint-file "
        "<0600-export> [--apply]`; it is dry-run-default, conflict-refusing, "
        "and returns only redacted digests. The admin registered stack-config "
        "result is metadata-only; `yoke projects pulumi-stack-config get "
        "--project <slug> --stack <name> --output <file>` fetches the body via "
        "no-store into a 0600 file. For a new explicitly declared stack, the "
        "client-local/source-dev bootstrap is `yoke pulumi exec --project "
        "<slug> --stack <name> -- init --secrets-provider "
        "'awskms://<kms-alias>?region=<region>'`. It materializes a 0700 "
        "scratch workspace, requires the exact `stacks` declaration, and "
        "persists typed operator-state; no repo-local infrastructure checkout "
        "is required. Then use `yoke pulumi exec --project <slug> --stack "
        "<name> -- <preview|refresh|import|up|stack output NAME ...>`; "
        "single-name output reads never allow `--show-secrets`; `up` is "
        "local/operator-only and requires both `--yes` and `--non-interactive`. "
        "Local AWS and GitHub authority comes from capability files and the "
        "selected service binding. Actions keeps AWS OIDC; runner-fleet gets "
        "its narrow repository token from the hosted broker. "
        "The diagnostic all-capability SQL shape remains `SELECT type, settings "
        "FROM project_capabilities WHERE project_id = ?`; routine reads use the "
        "registered command instead. The Python workhorse is "
        "yoke_core.domain.projects_capabilities_settings; do not import settings "
        "helpers from projects_capabilities (wrong guess — that module owns "
        "capability listings and secrets). There are NO `project`, "
        "`capability_type`, `capability`, `key`, or `value` columns; those are "
        "stale guesses for this table."
    ),
}


__all__ = ["PROJECT_CAPABILITIES_TABLE"]
