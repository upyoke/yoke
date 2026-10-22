# Install

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Get started](index.md) > Install
<!-- /yoke:breadcrumbs -->

Install the released CLI and connect this machine through setup. For the
complete path from a new machine to its first work item, follow
[Get started](index.md); project-only installation and removal have their own
pages below.

```bash
curl -fsSL https://upyoke.com/install | sh
yoke setup
yoke status
```

To keep your harness permission settings unchanged, run
`curl -fsSL https://upyoke.com/install | sh -s -- --skip-harness-permissions`;
the installer passes the flag to the `yoke setup` it starts or names.

Prerequisites: a shell and `curl`. The installer installs `uv` automatically
when it is missing. Yoke supports Python 3.11–3.14. When no supported interpreter is
available, uv downloads a managed one automatically for the installer and
`yoke update`, without changing your system Python. Native Windows is a best-effort
compatibility path requiring Python 3.12 or newer; WSL follows the Linux path.
Run installation, onboarding and harness CLIs inside the WSL Linux filesystem
with systemd enabled. To open a URL in the Windows browser, Yoke tries
`wslview`, then `explorer.exe` if Python's browser opener fails. Install `wslu`
or enable Windows interop/PATH when both are unavailable. Verify the local UI
through Windows localhost forwarding before changing WSL networking modes.
Install and onboard Apply disable WSL2 idle shutdown through the Windows user
profile `.wslconfig` (WSL 2.5.4 or newer). Older WSL or unavailable Windows
interop warns without blocking completion; run `wsl --update` from Windows
and retry `yoke wsl setup`. Preview does not write WSL configuration.
Follow the printed `wsl --shutdown`
restart step when setup changes it; afterward terminals can close while the
relay and background work continue. After a deliberate distro shutdown, run
`yoke init --local` to restart its Postgres authority; it preserves your active
connection. See [local connection repair](../verification/local-connection-repair.md).
See [Yoke on Windows (WSL)](windows-wsl.md) for filesystem, systemd, and agent setup.

Local mode on macOS requires **macOS 26.0 or newer** on Apple Silicon and
Intel. The pinned embedded PostgreSQL 17.10.0 build sets this minimum.
Before downloading or initializing it, Yoke refuses older systems with
`embedded_postgres_macos_unsupported`, stating the detected and minimum
versions. An unreadable version refuses as `embedded_postgres_macos_version_unknown`.
Upgrade macOS and retry, or choose **A team server** or **upyoke.com** in
`yoke setup`; connecting to a remote core does not run embedded PostgreSQL.
See [Modes](modes.md#local).

Linux requires glibc (for example Ubuntu, Debian, or Fedora); musl hosts such as Alpine are refused before installation.
Amazon Linux 2 on arm64 is unsupported: its glibc is too old for the aarch64 psycopg wheels.

If Python's automatic download fails or downloads are disabled, the installer
reports `supported_python_unavailable`. Check network access and uv's Python
download settings, or run `uv python install ">=3.11,<3.15"`, then rerun the
installer or `yoke update`.

Yoke creates `~/.yoke` and missing private state and secret directories with
mode `0700`, including when the shell uses umask `002`. Existing directories
keep their permissions. If the machine-config lock refuses a group- or
world-writable `~/.yoke`, run `chmod 700 ~/.yoke` and retry. For a custom machine
home, use the exact directory and `chmod` command named in the refusal.
Select an isolated config with `YOKE_MACHINE_HOME=/tmp/yoke-worker yoke status`;
that home takes precedence over a config-file environment override. See
[Machine config](../cli/machine-config.md#machine-config) for selection and write ownership.

## Onboard wizard

`yoke setup` is a full-screen wizard:

1. **Install / PATH** — checks required tools and repairs PATH automatically,
   then opens Account. Install appears only when a check fails or a required
   tool is missing; fix the named cause and choose **Retry Install**. Review
   and the final summary list any shell files changed by uv.
2. **Account** — where Yoke lives (this machine / team server / upyoke.com)
3. **GitHub** — optional App connect for product GitHub commands
4. **Project** — create, clone, import, or bind a checkout. A clone is
   fetched here, not at Apply, so you see what the repository holds — and
   decide what happens to any Yoke files it already carries — first
5. **Review** — check compact change counts, then Apply. **Show all changes**
   lists applicable configuration and hook-trust writes; **Show summary** returns
   to the counts. Shell PATH files changed during Install are already applied
   and stay changed if you cancel. Worker launches bypass command approval;
   Codex workers also bypass the sandbox and CLI hook-trust checks. Expanded
   Review names the actual launch arguments. Saved operator settings stay in
   place; missing permission modes are seeded for unattended use.

Anything the wizard already finds — a checkout carrying Yoke files, a
repository that already has a project, a checkout already mapped on this
machine — is announced before you answer anything, and connecting to what
exists is the default. The mouse scrolls and clicks normally; on any screen
showing a URL or a one-time code the footer names a copy key (`^y`) and an
open-in-browser key (`^o`) instead of a native drag-select.

Before every TUI browser step, setup says “Opening your browser…”. Ctrl-Y
copies the current code or link; Ctrl-O opens the link again. Yoke sign-in
opens the complete link with the code pre-filled. GitHub documents entering
its code at the device page, so setup offers copy rather than adding an
unsupported pre-fill parameter.

From a coding agent, or anywhere without a terminal, `yoke setup` runs in
agent mode: it asks these same questions one at a time as JSON lines, and the
agent relays each one to the person. See [Agent setup](agent-setup.md)
for the loop, browser steps and refusals. `yoke setup --tui` forces the
wizard; `yoke setup --agent` forces agent mode.

When a checkout's Yoke files link it to a project that the chosen Yoke install
doesn't have or that your account can't access — typically left over from an
earlier install — the wizard says so and offers **Unlink and set up fresh**.
Nothing is written until you confirm Apply.

For **A team server**, follow [teammate invitations and machine connections](../projects/teammate-invitations.md).

Flags: `--yes` for non-interactive apply; `--local` or `--connect URL` to skip
the destination picker.

To start a new install from a backup, run `yoke setup`, choose **This machine**
or **Host a server here**, then **Start from a backup**. Select the portable
`.tar` made by uninstall with backup or the web export panel. Setup validates
it immediately with `yoke universe validate`; the backup carries the account,
so there is no name prompt. Review the account and destination, then choose
**Apply** to run the existing local or self-host import. Import replaces that
destination's database and revokes imported credentials. Project setup then
offers the restored projects and asks where their code lives on this machine;
the universe backup carries project data, not repository folders or external
services. **A team server** and **upyoke.com** keep their sign-in flows; hosted
imports use the dashboard portability panel.

## After onboard

The installer runs `yoke path fix --yes` and verifies every installed supported
shell: zsh, bash and fish. Yoke prepends marked, idempotent PATH blocks in
`.zshenv` and `.zprofile`, Bash's selected login file and `.bashrc`, and fish's
`config.fish`. `ZDOTDIR`, `XDG_CONFIG_HOME`, and the configured tool bin directory
are respected. The `.bashrc` block precedes interactive-only guards so SSH
commands can find Yoke. Open a new terminal after installation.

Plain `bash -c` inherits PATH from its parent: the check starts it from a fresh
login/interactive shell. A completely stripped Bash environment reads no user
startup file; supply PATH or BASH_ENV explicitly in that case. Yoke preserves
an existing BASH_ENV setting. Zsh and fish read their startup files for direct
non-login commands. Uninstall removes Yoke's marked blocks and preserves other
shell content, including PATH entries owned by the user or another tool.

```bash
yoke status          # machine, env, credentials, checkouts
yoke ui up           # local daemon, or the connected self-host workbench
# or open the Cloud dashboard after sign-in
```

On a team server, `yoke ui up` opens company sign-in when configured. Otherwise
it uses the connection's API token to open a single-use browser sign-in link
for that actor. The link expires in two minutes; rerun the command if needed.
Sign-in links are never printed, including in JSON. If a browser cannot open
or an agent runs the command, run `yoke ui up` from your own terminal on a
machine with a display.

Upgrade later with `yoke update`: it reruns the official installer with
onboarding disabled from this machine's recorded distribution origin and
channel (`settings.distribution` in `~/.yoke/config.json`), then reports the
verified old and new version or that you're already current. Without that
record it refuses; select one with `yoke settings set distribution --origin URL
--channel NAME`. `--channel NAME` selects and saves another channel;
`--version VERSION` installs that exact release. `yoke update --check [--json]`
installs nothing: it proves the installed build, then reports the active
server's engine and the channel's latest, with `behind: cli|server|none` and
the next step. The proof reads the full source commit the installed CLI wheel
was built from (`source_commit`) and lists that release's published wheel
sha256 values (`wheels`); it refuses with `installed_build_mismatch` and the
exact reinstall command when the commit differs from the release manifest's.
`yoke --version` prints only the version. On the
local universe `yoke update` updates the CLI and local server together; a team
server's admin upgrades it; hosted servers update with each hosted release.

Install, reinstall and upgrade restart the machine's hook evaluator and check
that it answers; on failure, read the named log, run `yoke hook resident
restart` and retry. Hook timing stays in the diagnostics log. Setup also
writes Yoke's machine-wide hooks into each existing harness home's user config,
so sessions outside a project register; inside one, the project's hooks run.

The installed CLI follows your active connection (`active_env`, set by
`yoke env use`) automatically, whether that is upyoke.com, a self-hosted server
or a fork's own plane: each time that connection's relay observes its server
serving a new release it restarts on that release and installs exactly that
version as this machine's CLI, recording the outcome in
`operator-cli-follow.json` in the relay's state directory. Relays for other
connections never touch the CLI, and nothing runs on a schedule. When the CLI
is still older than the release the active connection serves, commands sent to
it print one warning naming `yoke update --version VERSION`; they never update
or refuse on their own. A local universe needs none of this: its server is the
installed CLI.
The installer builds each CLI release in its own uv tool directory and swaps
one launcher pointer atomically. Running commands keep their original modules;
new commands use the published release. Old environments retire after their
commands finish; cleanup failures name the reason and the update to retry.
The installer repairs git credential-helper references for the new release.

Every successful install or reinstall restarts a running machine-local
dashboard with the newly installed executable. It keeps the same environment,
host, port and bookmark, opens no browser, and leaves a stopped dashboard
stopped. This also covers upgrades through `yoke update` and
`yoke self-host upgrade`, which use the public installer. A restart failure
fails installation before the ready message and names the recovery; after
repairing it, rerun the installer. Hosted and team-server dashboards follow
their server deployment lifecycle.

When run inside an installed project, `yoke update` also runs
`yoke project refresh` with the updated executable, even when the CLI version
is already current. A refused or incomplete project refresh fails the update
with `project_update_incomplete`; the CLI remains installed, and the refusal
names how to finish the project refresh. Outside an installed project there
is no project refresh. Source checkouts retain their `yoke dev setup` owner.

`yoke update` and `yoke self-host upgrade` refuse to replace an active Yoke
source-checkout install with packaged releases. Update that checkout with git;
for a server built from it, rebuild through
`yoke core upgrade --from-checkout /path/to/yoke --build`.

The first command you run after an upgrade brings the rest of the install up
to the new engine. A machine-local universe has its schema converged before
the command is served — the same step a hosted container runs on boot.
Additive foreign keys match the live `environments.id` type so a universe
still on text keys reaches the ordered history that converts them. Every control-plane connection declares a bounded `idle_in_transaction_session_timeout` and TCP keepalives as libpq startup options, so an abandoned transaction releases its locks without an operator and a half-dead forward is noticed rather than waited on. That is a property of the connection, which is what makes it hold whatever role the client authenticates as — a role default is scoped to one `(role, database)` pair, so a client connecting as an admin role inherits that role's value rather than the serving role's. The convergence additionally records the same bound as the role's database default, for sessions Yoke did not open; that write is best-effort, so a role that cannot alter its own defaults — or a second boot racing on the same catalog row — degrades with an `application_role_default_not_persisted` diagnostic on stderr instead of refusing every read. A project
checkout whose operating layer predates the new engine is named once, with
the `yoke project install <checkout>` that refreshes it. Run that when it
appears; otherwise the checkout keeps teaching the previous release.

## Related

- [Maintaining a private fork](../projects/private-forks.md)
- [Modes](modes.md)
- [CLI and config](../cli/index.md)
- [Projects](../projects/index.md)
- [Project installation](project-install.md)
- [Remove Yoke](uninstall.md)
- [Get started](index.md)

Run `yoke path check --json` to see login, interactive, non-login and SSH
results for each installed supported shell. Any unresolved or shadowed Yoke
sets `needs_fix=true` and exits nonzero with a named context and recovery.
Run `yoke path fix --yes`, open a new terminal, and retry `yoke path verify`.
If repair still fails, check the named shell startup files for PATH overrides
and file permissions. Setup uses the same repair and verification.
