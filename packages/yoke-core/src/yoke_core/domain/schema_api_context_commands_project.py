"""``project`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``project``
topic entries: project test-command read/list helpers used by Engineer
and Tester for project-scoped verification commands.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


PROJECT_COMMANDS: list[dict] = [
    {
        "topic": "project",
        "purpose": "List available, installed, and stale project Packs",
        "recipe": "yoke packs list --project <project> [--json]",
        "notes": (
            "Registered read packs.catalog.list works over HTTPS, self-hosted, "
            "and local transports. Repository .yoke/packs.json is authority; "
            "the DB row is a timestamped UI/search projection and may be stale."
        ),
    },
    {
        "topic": "project",
        "purpose": "Preview or install one reusable project capability",
        "recipe": (
            "yoke packs get <pack> <checkout> --project <project> "
            "[--version <version>] [--apply]"
        ),
        "notes": (
            "Preview is default. Apply installs the selected Pack and any "
            "missing declared dependencies, writes ordinary project-owned "
            "source, and records the result in .yoke/packs.json. Projects are "
            "expected to customize the installed code."
        ),
    },
    {
        "topic": "project",
        "purpose": "Preview or update one installed project Pack",
        "recipe": (
            "yoke packs update <pack> <checkout> --project <project> "
            "[--version <version>] [--apply]"
        ),
        "notes": (
            "Preview is default. Update reconstructs the old immutable Pack "
            "version and three-way-merges the new version with project "
            "customizations. Overlapping edits are explicit conflicts; removed "
            "upstream files are retained and unrelated project files are ignored."
        ),
    },
    {
        "topic": "project",
        "purpose": "Read project test command for a scope",
        "recipe": (
            "yoke project-structure command-definitions get "
            "--project <project> --scope quick"
        ),
        "notes": (
            "Registered read project_structure.command_definitions.get "
            "(works over https). Scopes: quick, full, e2e, smoke. Empty "
            "stdout means the project/scope has no command configured; do "
            "not invoke the raw command_definitions module from packets."
        ),
    },
    {
        "topic": "project",
        "purpose": "List configured project test commands",
        "recipe": (
            "yoke project-structure command-definitions list --project <project>"
        ),
        "notes": (
            "Registered read project_structure.command_definitions.list "
            "(works over https). Prints scope=command lines in canonical "
            "scope order; empty stdout means no project test commands are "
            "configured. Deploy default: yoke project-structure "
            "deploy-defaults get --project <project> "
            "(project_structure.deploy_defaults.get); empty stdout means "
            "no default; do not invoke the raw deploy_defaults module."
        ),
    },
    {
        "topic": "project",
        "purpose": "Update an ephemeral environment row field",
        "recipe": "yoke ephemeral-env update <env-id> status healthy",
        "notes": (
            "Registered write ephemeral_env.update (works over https). Use "
            "for status, workflow_run_id, url, and deployed_sha updates on "
            "ephemeral_environments rows; the handler preserves cmd_update "
            "semantics including stopped_at auto-set for terminal statuses. "
            "Do not teach the retained domain-update command for lifecycle writes."
        ),
    },
    {
        "topic": "project",
        "purpose": "Migrate legacy Pulumi operator state",
        "recipe": (
            "yoke projects pulumi-state migrate --project <project> "
            "--site-id <site> --stack <stack> [--apply]"
        ),
        "notes": (
            "Migration is dry-run-default and exact-set, persists a durable "
            "retry marker, and returns redacted metadata. Stack-config "
            "registration is admin metadata-only; fetch its body through the "
            "no-store boundary with `yoke projects "
            "pulumi-stack-config get --project <project> --stack <stack> "
            "--output <file>`; execute it with `yoke pulumi exec --project "
            "<project> --stack <stack> -- preview` (also allows refresh and "
            "safe file-form import). Runner-fleet recovery may add "
            "`--bootstrap-local-authority` to mint narrow repository "
            "authority from capability-owned AWS secrets; other stack kinds "
            "and GitHub Actions refuse it. Local execution reads aws-admin "
            "from the machine capability store and resolves the selected service's "
            "repository-bound GitHub App authorization; Actions retains "
            "ambient OIDC credentials. Generic capability and operator-state "
            "surfaces are closed."
        ),
    },
    {
        "topic": "project",
        "purpose": "Execute a capability-owned Pulumi stack command",
        "recipe": (
            "yoke pulumi exec --project <project> --stack <stack> -- "
            "<init|preview|refresh|import|up|stack output NAME ...>"
        ),
        "notes": (
            "This is a client-local tool-shaped boundary, not a dispatcher "
            "function. Its canonical CLI adapter is "
            "`packages/yoke-cli/src/yoke_cli/commands/adapters/pulumi.py`; "
            "the execution workhorse is "
            "`packages/yoke-core/src/yoke_core/tools/pulumi_exec.py`. Never "
            "guess a sibling `commands/pulumi_exec.py` module. The selected "
            "stack must be declared in the project pulumi-state capability. "
            "Output reads require one exact output name and never expose "
            "secret values."
        ),
    },
    {
        "topic": "project",
        "purpose": "Register a live Pulumi checkpoint's operator state",
        "recipe": (
            "yoke projects pulumi-state checkpoint-import --project <project> "
            "--stack <stack> --checkpoint-file <owner-only-export> [--apply]"
        ),
        "notes": (
            "Use this typed dry-run-default boundary when an already-live "
            "stack has no legacy site settings to migrate. The CLI reads the "
            "0600 checkpoint locally, extracts only the awskms provider and "
            "encrypted data key, and returns a redacted receipt. Never copy "
            "another stack's operator state or write stack_state through raw "
            "SQL or generic capability-settings surfaces."
        ),
    },
]
