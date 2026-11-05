# Claude Code

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Agents](index.md) > Claude Code
<!-- /yoke:breadcrumbs -->

Yoke supports Claude Code CLI, desktop Code, and the editor surface. Shared
project instructions come from `AGENTS.md`; Yoke skills live in
`.agents/skills/yoke/` and Claude discovers them through
`.claude/skills/yoke`. See [Native discovery](harness-discovery.md) for the
supported engine floor and configuration checks.

## Start work

Open a session in the project folder and run `/yoke onboard` after setup.
Use `/yoke steer` next to review direction and staff work. The
[command reference](commands.md) lists the other Yoke skills.

Run `yoke doctor run --session` to check this session's registration,
Claude sign-in, and permission to run Yoke commands. Follow its named recovery.
Claude can load hooks installed during a conversation on the next prompt;
the readiness check tells you whether a new session is needed.

## Sign-in and discovery

The CLI's own authentication is separate from Yoke sign-in. Check it with
`claude auth status --json`; use `claude auth login` when signed out.
Setup can find Claude's bundled CLI even when it is absent from PATH.

Keep the built-in AGENTS plugin enabled. A conflicting `CLAUDE.md` can
suppress shared instructions under Claude's default configuration; the
[discovery guide](harness-discovery.md#claude-configuration) explains how to
load both without duplicating Yoke rules.

## Messages and launches

Hooks deliver orientation and messages through the shared Yoke engine.
Supported launch, resume, and wake behavior varies by surface: the installed
`.yoke/harness/claude/manifest.json` owns those capabilities. CLI worker
launches use the CLI surface; desktop chats require operator-driven re-entry.
See [Sessions](../sessions/index.md) and
[Claude operation rules](rules/claude-sessions.md).
