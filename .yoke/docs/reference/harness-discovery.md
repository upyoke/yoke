# Native project instructions and skill discovery

Shared project instructions live in one `AGENTS.md`. Skills live once in
`.agents/skills/yoke/`. These are separate native loading mechanisms:
an instruction file is always-loaded project guidance; a `SKILL.md` supplies
metadata at discovery and its body when invoked.

| Harness family and supported surfaces | Instructions | Skills |
| --- | --- | --- |
| Codex CLI, desktop, editor | Root and nested `AGENTS.md` | Native `.agents/skills`; no `.codex/skills` copy |
| Cursor CLI, desktop | Root and nested `AGENTS.md` | Native `.agents/skills`; no `.cursor/skills` copy |
| Claude Code CLI, desktop Code, editor | Native `AGENTS.md` on embedded engine >=2.1.281, with the built-in plugin enabled | Required `.claude/skills/yoke` symlink to `../../.agents/skills/yoke` |

The supported surface versions remain declared in each product harness
manifest's `session_control.surfaces`. The manifest's `cli.project_discovery`
declares the additional embedded-engine floor and native layout. Claude's
desktop app version is not its embedded Code engine version. Cowork is not a
project-Code surface and is not an installed project skill consumer.

## Claude configuration

Claude's default `claude-md-or-agents-md` loads AGENTS only when no `CLAUDE.md`,
`.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working directory or
any ancestor. Personal `~/.claude/CLAUDE.md` and managed organization
instructions do not suppress it. Refresh preserves project-specific Claude
content, including ancestor files; it refuses a configuration that would
silently suppress the shared rules.

When keeping such files, use `/config` to set **Project instructions** to
`claude-md-and-agents-md`. This preserves their instructions and loads AGENTS
once. Enable the built-in AGENTS plugin in `/plugin`, remove any
`claudeMdExcludes` matching AGENTS, run `claude update` if the engine is below
2.1.281, and start a new session. Verify the canonical path in `/memory`.
The first session after upgrading an older engine may still need a restart.

For file configuration, `instructionFiles` belongs in user settings, managed
settings, or an explicit `--settings` file. Claude ignores that plugin option
in project/local settings. Current engines use
`pluginConfigs.cc-plugin-agents-md@builtin.options.instructionFiles`; the
earlier plugin id `agents-md@builtin` is accepted by newer engines too.
Refresh reads user and managed files; an explicit launch settings file must
permit the same native loading. Bare/safe mode or strict plugin-only policy
that disables project skills is outside this supported configuration.

Yoke does not install a CLAUDE import or duplicate doctrine as a fallback.
An existing user-owned link/import may remain; Claude deduplicates an AGENTS
file it has already loaded. Ordinary prose saying “See AGENTS.md” is not an
import and does not guarantee loading.

## Refresh and ownership

Bundle schema 2 requires a matching CLI. An older bundle/CLI pairing refuses
and names the public-installer upgrade. Source previews, local/self-hosted
servers, and hosted servers render the same canonical tree and discovery
contract; wheels carry the same authored inputs.

Refresh deletes legacy skill copies only when every file has its original
matching install-manifest digest. Modified files, unexpected links, and
copies with no baseline cause `skill_discovery_ownership_ambiguous` before
project mutation. Move saved edits into the canonical skill tree and move the
obsolete entry outside skill discovery roots, then retry. Equal copies alone
do not prove installer ownership. For a cloned source-dev test checkout,
transfer the original manifest through `--manifest-from`; never fabricate it.

Legacy CODEX/CURSOR/CLAUDE managed blocks retire only with a matching recorded
block digest. Text outside their markers is preserved byte for byte.
`instruction_ownership_ambiguous` preserves all files and asks for the prior
baseline. Installer-created empty shells are removed; user-created files stay.

Native symlink support is required for the Claude skill entry. On Windows,
enable Developer Mode or administrator symlink permission and ensure Git
checks links out as links (`core.symlinks=true`). A filesystem without native
links receives `skill_discovery_link_unavailable` with recovery; Yoke does not
copy a second discoverable tree. Hooks, subagent adapters, and intra-skill
references retain their separate owners and canonical relative paths.

## Verify native discovery

After fresh install and repeated refresh, inspect the native skills menu:
each Yoke skill should appear once. For Codex, open the skill picker and search
Onboard. For Cursor, type `/onboard` without submitting it; distinguish Yoke's
description from Cursor's built-in Onboard. For Claude Code, inspect `/` and
`/memory` in a fresh supported session. Directory counts alone do not prove
native discovery or instruction loading.

Official sources checked 2026-10-08:

- [Codex AGENTS discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex skill discovery](https://learn.chatgpt.com/docs/build-skills)
- [Cursor rules](https://cursor.com/docs/rules)
- [Cursor skill directories](https://cursor.com/docs/skills)
- [Claude native AGENTS and configuration](https://code.claude.com/docs/en/memory)
- [Claude skill directories](https://code.claude.com/docs/en/skills)
