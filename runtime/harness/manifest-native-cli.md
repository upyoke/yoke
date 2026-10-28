# Native CLI launch and discovery

[Manifest schema](manifest-schema.md#native-cli) owns the parent contract.

The canonical source is `yoke_contracts.harness_cli_manifest`; renderers and
runtime consumers use that one registry rather than spelling harness commands
again.

| Key | Type | Description |
|-----|------|-------------|
| `surface_id` | string | Session surface served by this native command (for example, `codex-cli`). |
| `quota_source` | string | Relay quota adapter: `anthropic_oauth_usage`, `codex_account_rate_limits`, or `cursor_dashboard_usage`. Credentials stay on the executing machine; heartbeat readings carry values and named failure reasons. |
| `executable` | string | Command name the vendor installs (for example, `cursor-agent`). |
| `version_args` | list[string] | Arguments used by the bounded version probe. |
| `bundled_candidates` | list[string] | Optional absolute executable paths inside a vendor application bundle. Empty when no supported bundled command exists. |
| `bundled_patterns` | list[string] | Versioned executable patterns. `{version}` matches a dotted numeric release; `*` matches vendor build or architecture text. Expand `~` on the executing machine; choose the highest numeric version across patterns, then path to break ties. PATH and fixed candidates take precedence. |
| `install_command` | string | Official harness install command shared by Doctor and launch recovery. |
| `authentication` | object | Bounded status arguments, the optional JSON boolean sign-in key, and the native login arguments. Doctor records only the verdict, never the private native auth document. |
| `launch_environment` | object[string, string] | Environment values applied by the shared relay environment builder after stripping inherited harness state, before starting the native CLI. Subagents inherit these process values. |
| `background_time_limit` | string | Documented unattended command lifetime, launch-setting rationale and evidence, or an explicit designed deferral where no equivalent is documented. |
| `project_discovery` | object | Canonical instruction file, skill source, required native skill entry, minimum embedded engine version (nullable), and installed recovery document. Instruction-file discovery is independent of skill discovery. |

`project_discovery` applies to every surface in the family: Codex and Cursor
load `AGENTS.md` and `.agents/skills/yoke` natively. Claude requires an embedded
Code engine >=2.1.281 with its built-in AGENTS plugin enabled and instruction
configuration allowing AGENTS. Its `.claude/skills/yoke` discovery entry links
to the canonical tree. Install preflight refuses suppressed instructions and
ambiguous legacy ownership; see `.yoke/docs/agents/harness-discovery.md`.

Installer PATH repair reads this manifest registry, resolves each installed
command from the ambient installer PATH or a declared bundle candidate, and
adds stable resolved parent directories to login and non-login/SSH startup
surfaces. Versioned bundled directories are resolved on every lookup and never
added to shell PATH blocks because application updates replace them. Missing commands remain a reported, re-runnable state; the standard
Yoke tool directory is still added for later installs.


Claude declares `BASH_DEFAULT_TIMEOUT_MS=3600000`: a one-hour default for
unattended background commands, including foreground commands moved at their
timeout. This must exist before Claude starts, including its subagents; a Bash
export cannot configure the parent process. Explicit background commands select
their lifetime with `timeout`. The shared launcher reads the registry for every
harness, with no Claude-specific branch. Codex and Cursor declare empty launch
environments and a documented deferral for this Claude-only setting.
