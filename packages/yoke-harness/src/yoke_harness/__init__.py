"""yoke_harness — client-side agent-runtime adapters (sibling of yoke_cli).

Owns the Claude/Codex manifests + launchers, settings merge, hook *relay* (receive
event → forward), bootstrap orientation glue, and the fast LOCAL PreToolUse
guardrails (lints). Authority-bearing harness logic (session register, claim chain,
event emit, worktree mutation) lives in `yoke_core` and is reached over the API.
Rendered agent bodies/packets are served by core's install bundle, not vendored here.

May depend only on `yoke_contracts`, the `yoke_cli` client substrate, and the
transport client. MUST NOT import `yoke_core` or `runtime.api.*` / `runtime.harness.*`.
"""
