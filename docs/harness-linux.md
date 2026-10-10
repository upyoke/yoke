# Linux desktop config and plan-limit credentials

Claude desktop's existing config is read from
`$XDG_CONFIG_HOME/Claude/claude_desktop_config.json`, defaulting to
`~/.config/Claude/claude_desktop_config.json`. The installer seeds
`preferences.bypassPermissionsModeEnabled` only when absent; an explicit
`false` is preserved. It patches only an existing config file and reports
that Claude desktop must be restarted. The macOS path remains
`~/Library/Application Support/Claude/claude_desktop_config.json`.

The Claude Linux package's preference schema and config reader use the same
key and Electron user-data location. See [Claude's Linux installation
guide](https://code.claude.com/docs/en/desktop-linux) and
[Electron's platform paths](https://www.electronjs.org/docs/latest/api/app#appgetpathname).

Plan-limit probes keep credentials on the relay machine. On Linux, Claude
reads `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`); Cursor reads
`$XDG_CONFIG_HOME/cursor/auth.json` (`accessToken`), defaulting to
`~/.config/cursor/auth.json`. Cursor Agent's vendor file store owns this
format; sign in with `cursor-agent login` to create it. Missing or malformed
credentials report `stale_credential`; sign in again on that machine.
Tokens are used only for vendor requests and are excluded from readings.
Claude's usage check identifies itself as the installed Claude Code
(`claude --version`, read on each refresh); when that version is unreadable
the reading reports `claude_version_unreadable_<verdict>` and no request is
sent — repair the install so `claude --version` prints a version.
The macOS probes use the login keychain, with Claude's credentials-file
fallback. Linux probes never invoke the macOS `security` command.

These Linux paths also apply to apps running inside the WSLg distribution;
the relay and credentials must live in that distribution. Yoke's desktop
surfaces remain operator-opened. Use the target harness manifest and that
machine's app detection to establish its available desktop surfaces.
