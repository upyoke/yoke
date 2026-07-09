# Installer Testing Mac

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately -- before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Sub-guide for [Installer Testing](INSTALLER-TESTING.md).

Operator recipe for a reusable macOS host used to test the public Yoke
installer, `yoke onboard`, PATH repair, Git/Xcode recovery, visible terminal
rendering, and remote agent session registration. Normal lane:

```bash
curl -fsSL https://api.stage.upyoke.com/install | bash
```

Use prod only for explicit release smoke. Keep trials inside the test user's home; reset deletes Yoke, uv, token files, PATH blocks, and `~/code` children.

## Host And Access

Current physical host: `testy@100.117.161.86`, Tailscale private address,
host name `Mac`, `/bin/zsh`, Apple Silicon `arm64`.

Use Tailscale for private reachability and macOS Remote Login for SSH. Do not
expose SSH with router port forwarding. Use ordinary macOS SSH over Tailscale;
Tailscale SSH is not required. Drive acceptance through a real SSH TTY or a
visible Terminal.app session, not a scripted pseudo-run.

One-time setup:

1. Install Tailscale, sign into the operator tailnet, and allow the VPN prompt.
2. Create a dedicated macOS user, for example `yoke-tester`.
3. Enable Remote Login for that user.
4. Add the operator public key to `~/.ssh/authorized_keys`.
5. Disable sleep while testing.
6. Install/unlock Claude Code for remote agent smokes; use Screen Sharing or
   Remote Management for visual observation and GUI permission prompts.

Homebrew is optional. If `brew` is on `PATH`, installer `uv` setup and project
Git recovery can use it; otherwise Yoke uses Astral `uv` and Apple Tools Git.

## Remote Login And SSH Key

Preferred GUI path: System Settings -> General -> Sharing -> Remote Login,
then allow either all users or the dedicated test user. CLI path:

```bash
sudo systemsetup -setremotelogin on
```

Current macOS may require Full Disk Access for that CLI command. If prompted,
use the GUI path or enable Terminal under System Settings -> Privacy &
Security -> Full Disk Access and rerun it.

Run this in Terminal.app as the test user, replacing the placeholder key:

```bash
/bin/zsh <<'YOKE_SSH_SETUP'
set -eu
PUBKEY='PASTE_OPERATOR_PUBLIC_KEY_HERE'
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! /usr/bin/grep -qxF "$PUBKEY" "$HOME/.ssh/authorized_keys"; then
  printf '%s\n' "$PUBKEY" >> "$HOME/.ssh/authorized_keys"
fi
/usr/sbin/chown -R "$USER":staff "$HOME/.ssh"
sudo /usr/sbin/systemsetup -setremotelogin on || echo "Enable Remote Login in System Settings or grant Terminal Full Disk Access."
sudo /bin/launchctl enable system/com.openssh.sshd 2>/dev/null || true
sudo /bin/launchctl kickstart -k system/com.openssh.sshd 2>/dev/null || true
echo "DONE: SSH key installed for $USER"
YOKE_SSH_SETUP
```

Verify from the operator machine:

```bash
ssh -tt -e none -o BatchMode=yes -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=accept-new testy@100.117.161.86 \
  'printf "YOKE_SSH_OK user=%s host=%s shell=%s\n" "$USER" "$(hostname)" "$SHELL"; uname -a; id'
```

Use `-tt` for a real TTY. Use `-e none` so a leading `~` typed into the wizard
is delivered to the remote terminal instead of swallowed by the local SSH
client. Keep the host awake:

```bash
sudo pmset -a sleep 0 disksleep 0 displaysleep 0 powernap 0
```

## Token Files

Copy short-lived test tokens to `/tmp` on the Mac. Never paste token values
into shell commands or commit them to docs.

```bash
scp ./yoke-stage.token testy@100.117.161.86:/tmp/yoke-stage.token
scp ./yoke-prod.token testy@100.117.161.86:/tmp/yoke-prod.token
scp ./github-yoke-e2e.token testy@100.117.161.86:/tmp/yoke-github.token
ssh testy@100.117.161.86 'chmod 600 /tmp/yoke-stage.token /tmp/yoke-prod.token /tmp/yoke-github.token'
```

In the wizard, choose token-from-file and use `/tmp/yoke-stage.token` for
stage auth and `/tmp/yoke-github.token` for GitHub auth.

## Claude Code SSH Smoke

Install Claude Code while logged into the Mac as the test user:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Complete Claude login in the Mac's GUI Terminal. Claude stores the login in the
macOS keychain; plain SSH may not read that item. Export it to Claude's
SSH-readable file:

```bash
mkdir -p ~/.claude
security find-generic-password -a "$USER" -s "Claude Code-credentials" -w \
  > ~/.claude/.credentials.json
chmod 600 ~/.claude/.credentials.json
```

If SSH gets keychain status `36`, ask the logged-in Terminal.app to run it:

```bash
ssh testy@100.117.161.86 \
  'osascript -e '\''tell application "Terminal" to do script "mkdir -p ~/.claude; security find-generic-password -a \"$USER\" -s \"Claude Code-credentials\" -w > ~/.claude/.credentials.json; chmod 600 ~/.claude/.credentials.json"'\'''
```

Smoke from the operator machine:

```bash
ssh testy@100.117.161.86 \
  '/bin/zsh -lc '\''export PATH="$HOME/.local/bin:$PATH"; claude -p "Reply exactly: CLAUDE_SSH_OK"'\'''
```

Operator-side hooks require `lint_db_cmd_remote_claude_cli=warn` in
`.yoke/lint-config`; local `claude` CLI invocations remain blocked.

## Stage Installer

Run in a real TTY:

```bash
ssh -tt -e none testy@100.117.161.86
curl -fsSL https://api.stage.upyoke.com/install | bash
```

Manual proof path: accept `uv` install if missing, accept PATH repair, confirm
handoff into `yoke onboard`, pick upyoke.com on the destination picker, choose
stage, use `/tmp/yoke-stage.token` and `/tmp/yoke-github.token`, clone/import
under `~/code`, apply, and record the report path.

Post-run checks:

```bash
source "$HOME/.zprofile" 2>/dev/null || true
command -v uv; command -v uvx; command -v yoke; yoke --version
find "$HOME/.yoke/onboarding-runs/apply-reports" -maxdepth 1 -type f -print
grep -R '"final_status": "done"\|"secret_free": true' "$HOME/.yoke/onboarding-runs/apply-reports" || true
cd "$HOME/code/<project>"
git remote -v
git status --short --branch
test -f .yoke/install-manifest.json
test -f .yoke/BOARD.md
yoke status
yoke board
```

PATH repair must work in one-shot SSH too:

```bash
ssh testy@100.117.161.86 'command -v uv; command -v uvx; command -v yoke; yoke --version'
```

## Stage And Prod On One Mac

The Mac can keep both env credentials. Add or refresh a second env without
reinstalling the project:

```bash
yoke auth set stage --token-file /tmp/yoke-stage.token
yoke auth set prod --token-file /tmp/yoke-prod.token
yoke env use prod
yoke status
YOKE_ENV=stage yoke status
YOKE_ENV=prod yoke status
```

Interactive fallback for configuring prod without touching a project:

```bash
yoke onboard --env prod --api-url https://api.upyoke.com/v1 \
  --token-file /tmp/yoke-prod.token --project-mode machine-only --yes
yoke env use prod
```

Expected: no-env `yoke status` uses prod after `yoke env use prod`, while
`YOKE_ENV=stage yoke status` still reaches stage. A stage installer proof may
leave active env on stage; restore prod before normal operator use.

## Prod Local-Mode Cold-Start Smoke

Use this after a prod publish that changes the installer, local universe,
project install bundle, board rendering, or `yoke ui`. Start from
`Reset Between Runs`; that wipe is the ground truth that the next install is a
cold start. Keep evidence under the campaign root from the parent guide:
TTY text in `captures/`, screenshots in `screenshots/`, and UI screenshots in a
named subdirectory such as `screenshots/yoke-ui/`.

Run the product installer without launching the wizard, then exercise local mode
non-interactively:

```bash
ssh -tt -e none testy@100.117.161.86
curl -fsSL https://api.upyoke.com/install | bash -s -- --yes --no-onboard
export PATH="$HOME/.local/bin:$PATH"
yoke --version
yoke init --local --json
mkdir -p "$HOME/code/my-project"
cd "$HOME/code/my-project"
git init
yoke onboard project "$HOME/code/my-project" \
  --slug my-project \
  --name "My Project" \
  --default-branch main \
  --public-item-prefix MYPR \
  --github-adoption skip \
  --config "$HOME/.yoke/config.json" \
  --yes \
  --json
yoke local demo seed --project my-project --json
yoke board rebuild --print --no-pager
```

Capture the live TTY after each major step. For the installer and any visible
TUI step, use the region screenshot procedure in `Visual And Terminal Modes`;
the bridge log or SSH transcript is the fallback when macOS blocks image
capture.

Then prove the local dashboard:

```bash
cd "$HOME/code/my-project"
yoke ui --host 127.0.0.1 --port 8787
```

From the operator machine, tunnel the port and capture the dashboard in a local
browser:

```bash
ssh -N -L 8787:127.0.0.1:8787 testy@100.117.161.86
```

Open `http://127.0.0.1:8787`, verify the seeded items and board data are visible,
and save a screenshot under the campaign root. If Browser QA is available on the
Mac, a `yoke qa browser screenshot` capture is acceptable; otherwise the SSH
tunnel plus local browser screenshot is the required fallback.

## Session Registration And Telemetry Smoke

Use after a stage or prod publish that touches hooks, auth, session identity,
lane routing, telemetry, or board rendering. Run from visible Terminal or a
real SSH TTY so the user can watch the same terminal.

```bash
cd "$HOME/code/buzz"
YOKE_ENV=stage yoke status
YOKE_ENV=stage claude -p 'Reply exactly: YOKE_STAGE_SESSION_SMOKE_OK'
YOKE_ENV=stage yoke board rebuild --print --no-pager
```

The board should show a fresh Buzz session. Verify the control plane:

```bash
YOKE_ENV=stage yoke db read "SELECT session_id, project_id, actor_id, executor, display_name, model, execution_lane, workspace, ended_at FROM harness_sessions WHERE project_id = 2 ORDER BY started_at DESC LIMIT 5"
YOKE_ENV=stage yoke events query --project buzz --since '20 minutes ago' --limit 50
```

Expected stage evidence: `project_id=2`, executor/model/lane populated,
DB-backed lane such as `DARIUS`, no hook-denied errors, session events carrying
the same project id, and visible board newest session matching the DB row.
Angle-bracket Claude model values are temporary SDK placeholders and should be
upgraded by later concrete registration.

For hosted API logs, check CloudWatch from the operator machine with AWS
operator credentials, not from the test Mac:

```bash
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '"POST /v1/hooks/evaluate"'
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '?ERROR ?Error ?error ?Traceback ?Exception'
```

Expected CloudWatch evidence: hook relay requests return HTTP `200`, include
the expected actor/token/request ids, and the error scan is clean.

## Visual And Terminal Modes

SSH TTY output is authoritative. Screenshots are optional and depend on macOS
Screen Recording and Automation permissions; if direct SSH `screencapture`
fails, ask the logged-in Terminal.app to run it through `osascript`. For visible
TUI probes, keep the TUI attached to the Terminal TTY; redirecting stdout
through `tee` before Textual starts can make Textual paint a smaller rectangle.
After Yoke is installed, use the packaged bridge for logged visible TUI runs:

```bash
/Users/testy/.local/share/uv/tools/yoke-cli/bin/python \
  -m yoke_cli.config.visible_terminal_pty_bridge \
  --fifo /tmp/yoke-visible-tui.fifo --log /tmp/yoke-visible-tui-pty.log \
  --status /tmp/yoke-visible-tui.status -- \
  /usr/bin/env TERM=xterm-256color YOKE_ENV=stage \
  /Users/testy/.local/bin/yoke onboard --post-install
```

### Drive the wizard agent-driven, screen by screen

To run the `yoke onboard` wizard from the operator machine with no human at the
keyboard, while seeing each rendered screen:

1. Install non-interactively so no consent prompt blocks the run:
   `curl -fsSL https://api.stage.upyoke.com/install | bash -s -- --yes --no-onboard`.
   Then invoke `yoke` by absolute path (`--no-onboard` skips PATH repair):
   `/Users/testy/.local/bin/yoke`.
2. Run `yoke onboard` under the bridge above inside a Terminal.app window, so the
   TUI is the real visible app. Input comes from the FIFO, not the keyboard.
   Create the wizard window, set its final bounds, and only then launch the
   bridge in that existing window:

   ```bash
   osascript <<'OSA'
   tell application "Terminal"
     activate
     set wizardTab to do script "printf wizard-ready"
     delay 1
     set wizardWindow to front window
     set bounds of wizardWindow to {40, 60, 1540, 980}
     set wizardWindowId to id of wizardWindow

     set helperTab to do script "printf helper-ready"
     delay 1
     set helperWindow to front window
     set bounds of helperWindow to {40, 1000, 1540, 1220}
     set helperWindowId to id of helperWindow

     do script "zsh /tmp/launch.sh" in window id wizardWindowId
     return (wizardWindowId as string) & "," & (helperWindowId as string)
   end tell
   OSA
   ```

   Do not launch the bridge and resize the window afterward: Textual may keep
   the initial short terminal height for the active screen and leave the previous
   screen visible below it.
3. Send keystrokes by writing raw bytes to the FIFO — no window focus or extra
   permission needed: `printf '\r' > /tmp/yoke.fifo` (Enter),
   `printf '\033[B' > /tmp/yoke.fifo` (Down), plain text for input fields.
4. Screenshot each screen — three gotchas (do these or the capture fails
   silently):
   - **The Mac must be UNLOCKED and the display awake.** A lock screen hides the
     Terminal windows (you capture only the lock screen); an asleep display gives
     an all-black frame or "could not create image". Wake it first with
     `caffeinate -u -t 1`; a locked Mac needs a human to unlock it once.
   - **Do NOT use `screencapture -l <window-id>`.** Terminal's AppleScript window
     id is not a CoreGraphics window number, and Quartz/pyobjc isn't installed to
     look one up, so `-l` errors "could not create image from window". Use
     **region** capture of the window's own bounds: get them via
     `osascript -e 'tell application "Terminal" to get bounds of window id <WID>'`
     (→ `left,top,right,bottom`), then run
     `screencapture -R<left>,<top>,<width>,<height> -o /tmp/shot.png`
     **through Terminal.app** (`do script "…" in window id <HELPER_WID>`; Terminal
     holds Screen Recording permission, a direct SSH `screencapture` does not).
     Downscale with `sips -Z 1500 /tmp/shot.png`, `scp` back, view. (Helper script:
     the session scratchpad's `mac-capture.zsh` parks HELP below WIZ and region-
     captures.)
   - The **bridge log is the authoritative fallback** when screenshots are blocked
     (headless/locked): ANSI-strip it to read the current screen as text
     (`tr -d '\000' | perl -pe "s/\x1b\[[0-9;?]*[A-Za-z]//g"`).
5. Each keystroke needs a brief render wait before the capture. In the Claude
   harness that short sleep trips the long-command polling guard — add
   `# lint:no-polling-check` to those per-screen capture commands (they are
   interactive render-waits, not background-command polling).
6. **Timing:** some steps run a network check between screens (e.g. "Develop Yoke
   itself" verifies the PAT can read the repo before showing the checkout-folder
   prompt). Keystrokes sent before the next screen renders are dropped (input
   fields then report "A value is required"). Read the bridge log to confirm the
   expected screen is up before typing, especially into input fields.

### Source-dev post-apply checks + gotchas

After a "Develop Yoke itself" Apply reaches `final_status: done` and the TUI
exits, the **deferred editable install** prints `✓ Dev environment ready`.
Verify the on-disk ground truth: the tool-venv python resolves `yoke_core` from
`<checkout>/packages/yoke-core/src`, `.yoke/install-manifest.json` is
`mode: source-link`, `.claude/agents` is a symlink, `.git/hooks/pre-commit`
exists, the checkout is registered under `projects` in `~/.yoke/config.json`
(NOT a stray `yoke-machine-config.json`), and `YOKE_ENV=stage yoke status`
reaches stage. The Review screen shows two distinct sections —
`On this machine (~/.yoke)` (write plan) and `Already on this machine (~/.yoke)`
(reuse) — never one duplicated header.

Two gotchas:

- **`--no-onboard` skips the wizard's PATH repair.** A bare `--no-onboard`
  install leaves `yoke`/`uv` visible only to interactive shells (the managed
  block lands in `~/.zshrc`), so a one-shot non-interactive `ssh host 'command -v
  yoke'` finds nothing. The wizard's "Add yoke to my PATH" step writes
  `.zprofile` AND `.zshenv`, and only then does the one-shot SSH command resolve
  `yoke`. Run that step (or a full onboard) before asserting the one-shot-SSH
  PATH check — it is not a regression after `--no-onboard`.
- **Preserve tokens across a cold-start reset.** The reset wipes
  `/tmp/yoke-*.token`. To reset-then-reinstall while keeping auth, copy the token
  FILES to a reset-safe dir first (e.g. `~/yoke-smoke-tokens/`, outside every
  wiped path) and restore them to `/tmp` after install — never re-type the token
  value. When wiping that dir afterward, remove it with an explicit path, not a
  trailing glob: zsh aborts the whole `rm` line when a glob like `/tmp/yoke*.log`
  has no match, silently leaving the token backup behind.

Board rendering caveat: Terminal.app and iTerm2-style terminals render rich
art. GNU Screen, dumb terminals, and one-shot SSH commands with no `TERM`
render plain ASCII plus a terminal-mode explanation. This applies only to
terminal board commands such as `yoke board` and `yoke board rebuild --print`;
it must not block `yoke onboard`. Use `--no-pager` for one-shot SSH smokes so
the command cannot stop inside `less`.

## Git And Xcode Cases

macOS Git may be an Apple developer-tools shim. Do not use `git --version` or
`xcode-select -p` as no-CLT preflight checks; either can open Apple's installer
prompt before Yoke shows its recovery screen. Also avoid `/usr/bin/python3`
during no-CLT preflight because it can route through the same shim.

Noninvasive preflight:

```bash
printf 'git shim: '; command -v git || true
printf 'clt git: '; test -x /Library/Developer/CommandLineTools/usr/bin/git && echo present || echo missing
printf 'brew: '; command -v brew || echo missing
printf 'sudo -n: '; sudo -n true >/dev/null 2>&1; printf '%s\n' "$?"
```

Cases to prove:

- Already installed: `clt git: present`; project setup should not show Git
  recovery.
- No CLT, no Homebrew, no noninteractive sudo: Project shows `Git is required
  for project setup`; `Install Apple Tools` opens `/usr/bin/xcode-select
  --install`; Yoke waits on `Finish Apple's installer`; `Check again` verifies.
- No CLT, no Homebrew, noninteractive sudo: after `sudo -v` in the same visible
  Terminal process tree, Yoke installs `Command Line Tools for Xcode-*` with
  `softwareupdate -i`, switches to `/Library/Developer/CommandLineTools`, and
  verifies Git.
- Homebrew present: Yoke uses `brew install git`.

Evidence after real install:

```bash
xcode-select -p
git --version
find "$HOME/.yoke/onboarding-runs" -maxdepth 3 -type f -name '*.json' -print
```

Returning to no-CLT is system-level destructive setup and needs explicit
operator approval:

```bash
sudo rm -rf /Library/Developer/CommandLineTools
sudo xcode-select --reset || true
```

## Reset Between Runs

Run as the dedicated test user:

```bash
set -eu
rm -rf "$HOME/.yoke" "$HOME/.yoke-e2e-logs" "$HOME/.local/share/uv" \
  "$HOME/.local/state/uv" "$HOME/.cache/uv" "$HOME/.config/uv" \
  "$HOME/Library/Caches/uv" "$HOME/Library/Application Support/uv" \
  "$HOME/Library/Application Support/yoke"
rm -f "$HOME/.local/bin/yoke" "$HOME/.local/bin/uv" "$HOME/.local/bin/uvx" \
  "$HOME/.local/bin/env" /tmp/yoke-install /tmp/yoke-token \
  /tmp/yoke-stage.token /tmp/yoke-prod.token /tmp/yoke-github.token /tmp/github.token
[ ! -d "$HOME/code" ] || /usr/bin/find "$HOME/code" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
if [ -x /opt/homebrew/bin/brew ] && /opt/homebrew/bin/brew list --versions uv >/dev/null 2>&1; then
  /opt/homebrew/bin/brew uninstall uv
fi
for file in "$HOME/.zprofile" "$HOME/.zshenv" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile"; do
  [ -e "$file" ] || continue
  tmp="${file}.tmp.$$"
  /usr/bin/awk '/BEGIN YOKE MANAGED PATH/ {skip=1; next} /END YOKE MANAGED PATH/ {skip=0; next} /uv was installed/ {next} /\. "\$HOME\/\.local\/bin\/env"/ {next} /source "\$HOME\/\.local\/bin\/env"/ {next} !skip {print}' "$file" > "$tmp"
  mv "$tmp" "$file"
done
echo "YOKE_MAC_WIPE_OK"
```

Verify:

```bash
/bin/zsh -lic 'command -v yoke || echo yoke-not-found; command -v uv || echo uv-not-found; command -v uvx || echo uvx-not-found'
/bin/zsh -c 'command -v yoke || echo ssh-yoke-not-found'
```
