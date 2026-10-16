# Native project instructions and skill discovery

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Agents](index.md) > Native discovery
<!-- /yoke:breadcrumbs -->

Shared project instructions live in one `AGENTS.md`. Skills live once in
`.agents/skills/yoke/`. These are separate native loading mechanisms:
an instruction file is always-loaded project guidance; a `SKILL.md` supplies
metadata at discovery and its body when invoked.

| Harness family and supported surfaces | Instructions | Skills |
| --- | --- | --- |
| Codex CLI, desktop, editor (engine >=0.161.0) | Root and nested `AGENTS.md` | Native `.agents/skills`; no `.codex/skills` copy |
| Cursor Agent CLI (>=2026.10.01), IDE (>=3.14) | Root and nested `AGENTS.md` | Native `.agents/skills`; no `.cursor/skills` copy |
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
An existing user-owned link/import is accepted; Claude deduplicates an AGENTS
file it has already loaded. Ordinary prose saying “See AGENTS.md” is not an
import and does not guarantee loading. A parent CLAUDE.md link to the main
checkout’s AGENTS.md is accepted from that checkout’s Git worktree, wherever
the worktree lives. An explicit `@AGENTS.md` import resolves relative to its
instruction file; code examples do not count as imports.

## Refresh and ownership

Bundle schema 3 requires a matching CLI. An older CLI refuses and names the
public-installer upgrade. An older serving bundle refuses as
`installed_manifest_bundle_unavailable`; ask the control-plane operator to
serve a matching release, then retry refresh. Source previews, local/self-hosted
servers and hosted servers render the same canonical tree and discovery
contract; wheels carry the same authored inputs.

Refresh uses one canonical skill tree and Claude discovery link. An
unexpected entry at `.claude/skills/yoke` refuses as
`skill_discovery_entry_conflict`; preserve its contents outside that path and
rerun refresh. Codex and Cursor discover the canonical tree directly.

Install and refresh report `install_drift.missing`, `changed`, and `interrupted`.
Missing recorded files are restored. Changed files require the recorded digest,
resolved or archived release bytes, interrupted-apply digest, or installer-history proof;
real edits refuse as `install_drift_local_edits` before mutation. The local
`.yoke/install-pending.json` record identifies an unfinished apply. Rerun
`yoke project refresh` to complete it; preserve that record until recovery.
Git metadata locally excludes the recovery record even with an older bundle.
The record also stores exact planned intermediate settings and instruction
bytes, so a dirty interrupted checkout can resume without admitting new edits.
Bundle files and the final manifest use atomic replacement. Completion verifies
every recorded whole-file digest and retains the recovery record through the
installer-owned local commit. Publication proves current installer-owned paths.

Yoke source repo only: regenerate packaged release hashes from fetched annotated tags with `yoke dev run -- python3 -m runtime.api.tools.released_install_hashes --source-checkout /absolute/claimed/checkout` and commit the catalogue.

Native symlink support is required for the Claude skill entry. On Windows,
enable Developer Mode or administrator symlink permission and ensure Git
checks links out as links (`core.symlinks=true`). A filesystem without native
links receives `skill_discovery_link_unavailable` with recovery; Yoke does not
copy a second discoverable tree. Hooks, subagent adapters, and intra-skill
references retain their separate owners and canonical relative paths.

## Read installed capabilities

```text
cat .yoke/harness/codex/manifest.json
```

Read `.yoke/harness/<harness-dir>/manifest.json` for the installed release.
Directories are `claude`, `codex`, and `cursor`; `claude-code` uses `claude`.
`agent_wake` names wake support and its evidence, `session_control` names
message/launch routes, and `supports` names hook affordances. `unverified`
means the capability has no proof; it does not authorize guessing.
The existing install bundle publishes renderer-owned release bytes and
refresh manages their digests, restores missing files and resumes interrupted
application. Do not edit managed manifests to change capabilities.
If a manifest is missing, run `yoke project refresh` from this project.
If its serving bundle predates schema 3, follow the operator recovery above.
Local edits use the refresh refusal's recovery.

## Hook diagnostics

Human diagnostics inside Git and harness tools begin with “yoke (<hook>): ”,
for example “yoke (pre-commit): ERROR: file-line-limit gate blocked this commit.”
Follow the repair in that diagnostic. Successful checks and identity-only
post-commit snapshot scans stay quiet. Required orientation, instructions,
continuations, handoffs and recovery still arrive through their normal owner.
JSON replies, delivery markers and machine identifiers retain their wire form;
the shared context composer budgets the combined delivery for each harness.
Inspect hook configuration with `yoke hook --help`.

## Verify native discovery

Startup orientation is composed on the client and confirmed only after it
reaches an allow response. HTTPS skips the server lifecycle renderer. Local
universes mark supplied client context so lifecycle dispatch keeps registration
and resume handling without emitting a second orientation.

After fresh install and repeated refresh, inspect the native skills menu:
each native Yoke entry should appear once. For Codex, open the skill picker and search
Onboard. For Cursor, type `/onboard` without submitting it; distinguish Yoke's
description from Cursor's built-in Onboard. Claude Code discovers one `/yoke` router through its native link; invoke
nested commands as `/yoke onboard`. Inspect `/config` for Project instructions
and `/memory` in a fresh supported session. Directory counts alone do not prove
native discovery or instruction loading.

Official sources checked 2026-10-08:

- [Codex AGENTS discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex skill discovery](https://learn.chatgpt.com/docs/build-skills)
- [Cursor rules](https://cursor.com/docs/rules)
- [Cursor skill directories](https://cursor.com/docs/skills)
- [Claude native AGENTS and configuration](https://code.claude.com/docs/en/memory)
- [Claude skill directories](https://code.claude.com/docs/en/skills)

Codex and Cursor Agent floors name the native releases verified for this layout;
older engines receive `instruction_runtime_unsupported`. The installer probes
installed CLIs. Desktop users must verify their embedded engine separately;
the outer app version does not prove its discovery capabilities.

## Guard scope

Register a managed checkout with `yoke project register <checkout> --project-id <id>`.
Its subdirectories and Git worktrees share that project; an unrelated Git
repository nested inside it does not. A machine connection or a folder named
`.yoke` alone does not make a checkout managed.

Outside managed projects, hooks apply machine safety rules: privacy-database
protection, literal search quoting and unmatched path globs. Project rules
(such as main-commit and destructive-Git checks) apply inside managed projects.
Lane rules check the real lane and claim authority there, including on main.
Unmapped HTTPS clients finish machine checks locally without project registration.
All harnesses use the same applicability declarations.

`yoke hook evaluate PreToolUse --dry-run` shows the registered chain inventory;
it does not execute guards or prove a workspace is registered. A
`hook_guard_scope_missing` diagnostic names the undeclared guard; report it
with `yoke ouroboros field-note append --kind failed --evidence '<diagnostic>'`.
A `hook_scope_unavailable` diagnostic names the mapping or scope repair needed
before retrying. Required project messages and lifecycle delivery retain their
own handlers; guard scope does not redefine session lifecycle.

## Related

- [Operating with agents](index.md)
- [Agent operation homes](rules/index.md)
