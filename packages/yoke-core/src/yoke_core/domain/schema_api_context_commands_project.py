"""``project`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``project``
topic entries for project-scoped infrastructure and deployment context.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


PROJECT_COMMANDS: list[dict] = [
    {
        "startup_roles": (),
        "topic": "project",
        "purpose": "Inspect, get, or update a project Pack",
        "recipe": "yoke packs <list|get|update> --help",
        "notes": (
            "List works over every transport; get/update take `<pack> "
            "<checkout> --project <project> [--version V] [--apply]`. Preview "
            "is default. Apply writes project-owned source and .yoke/packs.json; "
            "update three-way-merges customizations and reports conflicts. The "
            "repository receipt outranks its timestamped DB projection. "
            "`--catalog served|lane|commit:SHA` picks the Pack source: lane is "
            "the default under `yoke dev run`; commit:SHA adopts a merged, "
            "unreleased version and the receipt records that source."
        ),
    },
    {
        "startup_roles": (
            "main_agent",
            "engineer_agent",
            "tester_agent",
            "qa_walker_agent",
        ),
        "topic": "project",
        "purpose": "Read one branch preview environment",
        "recipe": "yoke ephemeral-env get <project> <branch> --json",
        "notes": (
            "Registered read ephemeral_env.get (works over https). The result "
            "contains the environment row, including status, url, workflow run, "
            "ports, and deployed SHA. Use the actual worktree branch; do not "
            "guess a PREFIX-N branch or read the table directly."
        ),
    },
    {
        "startup_roles": (),
        "topic": "project",
        "purpose": "Read the project's default deployment flow",
        "recipe": ("yoke project-structure deploy-defaults get --project <project>"),
        "notes": (
            "Registered read project_structure.deploy_defaults.get works over "
            "https. Empty stdout means no project default is configured; do "
            "not invoke the raw deploy_defaults module."
        ),
    },
    {
        "startup_roles": (),
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
        "startup_roles": ("main_agent", "engineer_agent"),
        "topic": "project",
        "purpose": "Execute a capability-owned Pulumi stack command",
        "recipe": (
            "yoke pulumi exec --project <project> --stack <stack> "
            "[--confirm-destroy <stack>] -- <init|preview|refresh|import|up|"
            "destroy|stack rm --yes|stack output NAME ...>"
        ),
        "notes": (
            "This is a client-local tool-shaped boundary, not a dispatcher "
            "function. Its canonical CLI adapter is "
            "`yoke_cli.commands.adapters.pulumi`; "
            "the execution workhorse is "
            "`yoke_core.tools.pulumi_exec`. Never "
            "guess a sibling `commands/pulumi_exec.py` module. The stack runs "
            "from its checked-in infra/Pulumi.<stack>.yaml plus Yoke-owned "
            "`yoke:` values (read with pulumi.Config(\"yoke\")); a stack "
            "without that file refuses with pulumi_stack_file_missing. "
            "Every operation, init included, needs the file; init pins the "
            "pulumi-state KMS key and prints the secretsprovider and "
            "encryptedkey lines to commit, and Yoke stores neither. "
            "Output reads require one exact output name and never expose "
            "secret values. `destroy` (whole stack, never --target; requires "
            "--yes --non-interactive) and `stack rm --yes` (never --force, so "
            "Pulumi refuses a stack still holding resources) both require "
            "`--confirm-destroy` naming the exact stack, and refuse while an "
            "environment stack whose committed file has an empty origin_ip "
            "names the target as its pulumi.origin_vps_stack_name; set "
            "origin_ip in that committed config once the consumer no longer "
            "needs the VPS outputs. The guard needs the consumer config "
            "committed: outside a git checkout with a commit, or with "
            "uncommitted changes to infra/Pulumi.yaml or the consumer file, "
            "it refuses with pulumi_stack_consumer_uncommitted. Every run opens on stderr "
            "with a `rendering "
            "<checkout> @ <revision> (<infra/ state>)` line naming the tree "
            "the program was read from, so read it before trusting an "
            "unchanged count; uncommitted work under `infra/` is rendered "
            "and reported rather than ignored. "
            "There is no `--cwd`: the render root is the project's resolved "
            "checkout. Standing in a second working tree of that same "
            "repository refuses before any resource summary; run from the "
            "named checkout, or bind the tree with `yoke project register "
            "<checkout> --project-id <id>`. A child `401 Bad credentials` "
            "on api.github.com "
            "is `github_provider_unauthorized`: the github.Provider credential "
            "GitHub rejected, not AWS, and not proof the launch GITHUB_TOKEN "
            "expired (wrong guess — a process token can already read the same "
            "variables and environments). Restore with `yoke github status` "
            "and `yoke projects github-binding status --project <project> "
            "--json`; if those are healthy, replace or update the stack "
            "provider so refresh reads the process token."
        ),
    },
    {
        "startup_roles": (),
        "topic": "project",
        "purpose": "Init a checkout and create a private GitHub remote",
        "recipe": "yoke project git bootstrap CHECKOUT --project <project> --yes",
        "notes": (
            "Client-local project.git.bootstrap; default dry-run. "
            "Wrong guess: wizard-only git init."
        ),
    },
]
