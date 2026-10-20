# Role agent spawn

Spawn the dispatching file's `yoke-<role>` agent (on Codex, the installed
custom agent of that name) in your harness's form; its prompt fills
`prompt: |`.

<!-- BEGIN GENERATED: harness-role-spawn -->
Source: `yoke_core.domain.dispatch_descriptors.render_for_harness`.

- `claude-code`: `Agent tool: subagent_type: "yoke-<role>" prompt: |`
- `codex`: `codex agent: .codex/agents/yoke-<role>.toml prompt: |`
- `cursor`: `Task tool: subagent_type: "yoke-<role>" prompt: |`
<!-- END GENERATED: harness-role-spawn -->
