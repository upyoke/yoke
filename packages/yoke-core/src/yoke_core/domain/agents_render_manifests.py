"""Harness manifest rendering — Yoke-shaped manifest schema in one place.

Claude, Codex, and Cursor carry Yoke-shaped manifests in the schema documented
at ``runtime/harness/manifest-schema.md``. The renderer materializes each
from the dicts below so the manifest schema doc, the rendered files, and the
runtime consumers all see the same content.

When a manifest field changes, update the schema doc first, then the dict
below, then re-run the renderer. Drift between schema doc and rendered files
is caught by the doctor check ``HC-harness-substrate-drift`` (lane R / task 10).
"""

from __future__ import annotations

from yoke_contracts.harness_cli_manifest import harness_cli_manifest
from yoke_contracts.session_control import capabilities_for_harness


def _session_control(harness_id: str) -> dict:
    return {
        "source": "yoke_contracts.session_control.SESSION_SURFACE_CAPABILITIES",
        "surfaces": capabilities_for_harness(harness_id),
    }


_CLAUDE_CLI = harness_cli_manifest("claude-code")
_CODEX_CLI = harness_cli_manifest("codex")
_CURSOR_CLI = harness_cli_manifest("cursor")


# Claude manifest — runtime/harness/claude/manifest.json
CLAUDE_MANIFEST: dict = {
    "harness_id": _CLAUDE_CLI.harness_id,
    "cli": _CLAUDE_CLI.to_json(),
    "runtime_minimums": {
        "wrapper_only": "any claude-code build with bash tool support",
        "hook_enhanced": "any claude-code build (PreToolUse/PostToolUse hooks are stable)",
        "tested_locally": "claude-code with Opus 4.7",
    },
    "bootstrap": {
        "spec_path": "runtime/harness/bootstrap-spec.json",
        "mechanisms": [
            "harness_native_config",
            "user_prompt_submit_hook",
        ],
    },
    "identity": {
        "executor": "claude-code",
        "provider_source": "runtime",
        "model_source": "runtime",
        "workspace_source": "payload_cwd_then_git_root",
    },
    "supports": {
        "command_source": "shared_yoke_registry",
        "disabled_entrypoints": [],
        "disabled_downstream_paths": [],
        "optional_local_affordances": [
            "session_start_hook",
            "user_prompt_submit_hook",
            "pre_tool_use_hook",
            "post_tool_use_hook",
            "stop_hook",
        ],
    },
    "session_control": _session_control(_CLAUDE_CLI.harness_id),
    "worktree_hook_enablement": {
        "config_path": ".claude/settings.json",
        "operations": [
            "verify_hook_config",
            "seed_directory_approval",
            "verify_environment_export",
        ],
        "environment": {
            "root_variable": "YOKE_ROOT",
            "root_expression": "${CLAUDE_PROJECT_DIR:-$PWD}",
        },
    },
    "telemetry": {
        "canonical_source": "yoke_core",
        "optional_local_sources": ["hook_logs"],
    },
    "fallback": {
        "when_hooks_missing": "wrapper_only",
        "when_path_unsupported": "return unsupported to core",
    },
    "canonical_agents": {
        "source": "runtime/harness/bootstrap-spec.json#canonical_agents",
        "consumption": "generated",
    },
}


# Codex manifest — runtime/harness/codex/manifest.json
CODEX_MANIFEST: dict = {
    "harness_id": _CODEX_CLI.harness_id,
    "cli": _CODEX_CLI.to_json(),
    "runtime_minimums": {
        "wrapper_only": "any codex build with bash tool support",
        "hook_enhanced": "codex >= 0.128.0-alpha.1 with hooks enabled",
        "tested_locally": "0.128.0-alpha.1",
    },
    "bootstrap": {
        "spec_path": "runtime/harness/bootstrap-spec.json",
        "mechanisms": [
            "harness_native_config",
            "optional_session_start_hook",
        ],
    },
    "identity": {
        "executor": "codex",
        "provider_source": "runtime",
        "model_source": "runtime",
        "workspace_source": "payload_cwd_then_git_root",
    },
    "supports": {
        "command_source": "shared_yoke_registry",
        "disabled_entrypoints": [],
        "disabled_downstream_paths": [],
        "optional_local_affordances": [
            "session_start_hook",
            "user_prompt_submit_hook",
            "pre_tool_use_hook",
            "post_tool_use_hook",
            "stop_hook",
        ],
    },
    "session_control": _session_control(_CODEX_CLI.harness_id),
    "worktree_hook_enablement": {
        "config_path": ".codex/hooks.json",
        "operations": [
            "verify_hook_config",
            "mirror_hook_trust",
            "verify_environment_export",
        ],
        "environment": {
            "root_variable": "YOKE_ROOT",
            "root_expression": "${YOKE_ROOT:-$PWD}",
        },
    },
    "telemetry": {
        "canonical_source": "yoke_core",
        "optional_local_sources": ["hook_logs"],
    },
    "fallback": {
        "when_hooks_missing": "wrapper_only",
        "when_path_unsupported": "return unsupported to core",
    },
    "canonical_agents": {
        "source": "runtime/harness/bootstrap-spec.json#canonical_agents",
        "consumption": "generated",
    },
}


# Cursor manifest — runtime/harness/cursor/manifest.json
#
# Affordance caveat the schema cannot yet express per surface: on the
# non-interactive terminal agent (`cursor-agent -p`), the prompt-submit and
# stop hooks never fire — only the IDE surface delivers them — so
# orientation rides the session-start hook, which fires on both surfaces.
CURSOR_MANIFEST: dict = {
    "harness_id": _CURSOR_CLI.harness_id,
    "cli": _CURSOR_CLI.to_json(),
    "runtime_minimums": {
        "wrapper_only": "any cursor build with agent terminal support",
        "hook_enhanced": (
            "cursor-agent >= 2026.07.23 / Cursor IDE >= 3.14 (hooks.json v1)"
        ),
        "tested_locally": "Cursor IDE 3.14.7 + cursor-agent 2026.07.23-e383d2b",
    },
    "bootstrap": {
        "spec_path": "runtime/harness/bootstrap-spec.json",
        "mechanisms": [
            "harness_native_config",
            "optional_session_start_hook",
        ],
    },
    "identity": {
        "executor": "cursor",
        "provider_source": "payload",
        "model_source": "payload",
        "workspace_source": "payload_cwd_then_git_root",
    },
    "supports": {
        "command_source": "shared_yoke_registry",
        "disabled_entrypoints": [],
        "disabled_downstream_paths": [],
        "optional_local_affordances": [
            "session_start_hook",
            "user_prompt_submit_hook",
            "pre_tool_use_hook",
            "post_tool_use_hook",
            "stop_hook",
        ],
    },
    "session_control": _session_control(_CURSOR_CLI.harness_id),
    "worktree_hook_enablement": {
        "config_path": ".cursor/hooks.json",
        "operations": [
            "verify_hook_config",
            "verify_environment_export",
        ],
        "environment": {
            "root_variable": "YOKE_ROOT",
            "root_expression": "${CURSOR_PROJECT_DIR:-$PWD}",
        },
    },
    "telemetry": {
        "canonical_source": "yoke_core",
        "optional_local_sources": ["hook_logs", "transcript_logs"],
    },
    "fallback": {
        "when_hooks_missing": "wrapper_only",
        "when_path_unsupported": "return unsupported to core",
    },
    "canonical_agents": {
        "source": "runtime/harness/bootstrap-spec.json#canonical_agents",
        "consumption": "generated",
    },
}
