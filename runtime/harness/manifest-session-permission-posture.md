# Harness manifest: session permission posture

The `session_permission_posture` object of [`manifest.json`](manifest-schema.md)
is rendered from
`yoke_contracts.harness_session_permission_posture.CLAUDE_SESSION_PERMISSION_POSTURE`.
Only Claude declares it. It holds what `yoke doctor run --session` requires of
a person's Claude session, and the recovery each surface can actually reach.

Claude Code enters `bypassPermissions` only when it is enabled at launch: by
`permissions.defaultMode` in `~/.claude/settings.json`, or by
`--permission-mode bypassPermissions`. Shift+Tab reaches bypass permissions
only in a session started that way. Setup writes the default. Claude Code
v2.1.283 and later may ask once to change that default to `auto`; accepting
rewrites Yoke's value, and sessions then start in auto mode with bypass
permissions out of reach.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the fact. |
| `session_mode` | string | Hook-reported `permission_mode` the session check passes: `bypassPermissions`. |
| `default_setting` | string | Setting that starts new sessions in that mode: `permissions.defaultMode`. |
| `default_setting_path` | string | User settings file setup writes it to. |
| `default_rewrites` | list | Values Claude Code writes over Yoke's default on its own (`auto`). Uninstall reverts them like Yoke's own write. |
| `harness_acceptance_key` | string | Key Claude Code writes when a person accepts the bypass warning. Yoke never writes it; uninstall removes it when it was absent before setup. |
| `launch_command` | string | Command that starts one session in the mode whatever the default says. |
| `in_session_switch` | string | Key that cycles modes inside a session. |
| `surface_recovery` | object | Recovery per surface (`claude-cli`, `claude-desktop`, `claude-vscode`) when the default still names the mode. |
| `default_lost_recovery` | string | CLI recovery when the default no longer names the mode: repair the default with `yoke doctor run --only harness-setup --fix`, then start a new session. |
| `evidence` | string | The Claude Code documentation checked, and when. |

The `HARNESS_POSTURE_RESTRICTED` refusal reports the session's mode and the
default it read, names Shift+Tab as unavailable when the default no longer
starts sessions in bypass permissions, and gives the matching recovery.
