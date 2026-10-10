# Yoke Repo Internals (Codex)

## Harness contract references (yoke source dev)

These describe how Yoke's harness adapters are built and compared. They live in
`docs/`, which the install bundle does not ship, so they stay out of the shared
AGENTS.md instructions:

- [Harness Bootstrap Contract](harness-bootstrap.md) -- neutral startup expectations; §2 lists the full Tier 1 operator surface
- [Harness Adapter Template](harness-adapter-template.md) -- five-part adapter template
- [Hook Parity Map](hook-parity-map.md) -- tier-by-tier hook classification across harnesses, including the Codex `PostToolUseFailure` gap

## Bootstrap render (yoke source dev)

Hooks inject orientation at session start. To print the full bootstrap
without relying on hook injection:

```sh
yoke dev run -- python3 -m yoke_core.hooks.bootstrap render-full --spec runtime/harness/bootstrap-spec.json --root .
```

That loads the neutral startup reads
defined by `runtime/harness/bootstrap-spec.json`, the shared prompt doctrine
and startup command output required by the [Harness Bootstrap
Contract](harness-bootstrap.md). `yoke_core.domain.main_agent_packet` adds the
startup trust/authority block and packet discovery commands; it does not embed
a role packet. Read `yoke packets render --role main_agent --topic T --detail full`
when that schema or operation depth is needed.

Codex Desktop opens this repo directly:

```sh
codex app .
```

Session identity comes from the hook pack: `.codex/hooks.json` sets
`YOKE_EXECUTOR` and `YOKE_PROVIDER` on every hook invocation, and the model
and entrypoint resolve from the Codex runtime. Nothing needs to be exported
into the shell by hand.

## Skill resolver (yoke source dev)

Thin wrappers, docs, and non-native tooling that need to enumerate or resolve Yoke skills use the Yoke-owned resolver on the bootstrap path:

```sh
yoke dev run -- python3 -m yoke_core.hooks.bootstrap skill-list --root "$YOKE_ROOT"
yoke dev run -- python3 -m yoke_core.hooks.bootstrap skill-path <skill-name> --root "$YOKE_ROOT"
```

The resolver always returns the canonical `.agents/skills/yoke/.../SKILL.md` path and never falls back to home-directory guesses like `~/.agents` or `~/.codex/skills`.

## Hook pack & manifest (source layout)

Yoke keeps the canonical Codex hook pack at `runtime/harness/codex/hooks.json`, surfaced to Codex via `.codex/hooks.json`; current Codex builds inject the session-start bootstrap automatically. The Codex capability manifest is at `runtime/harness/codex/manifest.json` — it declares adapter identity, runtime affordances, telemetry posture, and explicit limitations, and does not copy the shared Yoke command/path list. Conduct renders the shared agent bodies into Codex custom agents at `runtime/harness/codex/agents/yoke-*.toml`, surfaced at `.codex/agents/yoke-*.toml` from the canonical bodies under `runtime/agents/`. Adapter directory convention: [Harness README ](../runtime/harness/README.md).
