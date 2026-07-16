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
            "yoke project-structure command-definitions list "
            "--project <project>"
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
        "purpose": "Read or CAS-merge deployment environment settings",
        "recipe": (
            "yoke projects environment-settings merge --project <project> "
            "--environment-id <id> --set pulumi.activation_state=render_only"
        ),
        "notes": (
            "Registered projects.environment_settings.get/merge surfaces "
            "work over local, self-hosted, and hosted transports. The server "
            "verifies that environments.site belongs to the named project "
            "and performs a read-merge-CAS loop. The similarly named "
            "environment-merge-settings domain command is local-only and "
            "must not be used for an HTTPS authority."
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
]
