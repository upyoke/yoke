"""Harness manifest rendering — Yoke-shaped manifest schema in one place.

Both Claude and Codex carry Yoke-shaped manifests in the schema documented
at ``runtime/harness/manifest-schema.md``. The renderer materializes both
from the dicts below so the manifest schema doc, the rendered files, and the
runtime consumers all see the same content.

When a manifest field changes, update the schema doc first, then the dict
below, then re-run the renderer. Drift between schema doc and rendered files
is caught by the doctor check ``HC-harness-substrate-drift`` (lane R / task 10).
"""

from __future__ import annotations


# Claude manifest — runtime/harness/claude/manifest.json
CLAUDE_MANIFEST: dict = {
    "harness_id": "claude-code",
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
    "harness_id": "codex",
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
