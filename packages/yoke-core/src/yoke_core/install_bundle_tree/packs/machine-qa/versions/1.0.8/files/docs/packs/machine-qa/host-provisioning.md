# Provisioning a controlled macOS host

Machine QA drives a real macOS machine: it opens Terminal windows, reads the
screen, injects keystrokes, and reaches the host over SSH from a private
network. This document is the general provisioning contract for that host. It
names no host, credential, account, or project — those live in the installing
project's own capability record and machine-local secret files.

Follow it once per physical host, in order, before saving its
`test-machine:<resource-name>` capability row. Every step ends in an observable
check. A host that skips a step
usually fails later in a way that reads as agent confusion rather than as
missing machine state, which is why each check is stated as a command whose
output you can look at rather than as something to remember doing.

## 1. Account and identity

1. Create a dedicated macOS user for testing. Its short name is the account
   every baseline and reset operation is bound to; choose it before the first
   run and do not rename it afterwards.
2. Set the computer name deliberately. The private-network hostname is derived
   from it, and the capability stores that name.

Check:

```text
id -un && scutil --get ComputerName && scutil --get LocalHostName
```

## 2. Reachability by a stable name

Join the host to a private network (Yoke does not require a particular one)
and register it under a name you control.

**Store the name, not the address.** A rebuilt or re-registered host is a new
node and is assigned a new address, so an address saved in the capability
silently stops resolving the moment the machine is rebuilt — and the failure
surfaces as an unreachable capability rather than as a stale setting. If you
are rebuilding an existing host, delete its old node registration *before* the
rebuilt machine authenticates, or the name is taken and the new node registers
under a suffixed variant.

Check, from the machine that will run the QA runner:

```text
ssh <test-user>@<stable-host-name> true && echo reachable
```

## 3. Remote Login, and full disk access for remote sessions

In **System Settings → General → Sharing**:

1. Turn **Remote Login** on for the test user, and install the operator public
   key in the account's `~/.ssh/authorized_keys`. Do not expose SSH through
   router port forwarding.
2. In that same pane, turn on **Allow full disk access for remote users**.

The second toggle is separate from the first and is easy to miss. Without it
an SSH session cannot read large parts of `~/Library`, so any capture or
inspection of host state is silently incomplete: the commands succeed and the
protected subtrees are simply absent from the result. It is granted to the SSH
daemon's helper, not to your shell.

Check — the grant is present when the privacy database holds
`kTCCServiceSystemPolicyAllFiles` for `/usr/libexec/sshd-keygen-wrapper`:

```text
ssh <test-user>@<host> "sqlite3 '/Library/Application Support/com.apple.TCC/TCC.db' \
  \"select service,client,auth_value from access \
    where service='kTCCServiceSystemPolicyAllFiles'\""
```

Any process that performs a whole-home capture or restore must hold this
grant. Assert the grant rather than assuming a channel: SSH holds it by
default on a host provisioned this way, and Terminal holds it only if it was
granted separately, so a check that tests "am I running over SSH" passes on a
host where the grant was later revoked.

## 4. Disk encryption off

Turn **FileVault off**.

With FileVault on, a restart parks the Mac at the pre-boot unlock screen. That
screen has no network, so a headless host never comes back from a reboot and
cannot be recovered remotely. A controlled test host trades encryption at rest
for the ability to survive a restart unattended; it should therefore hold no
data that matters if the machine is lost.

Check:

```text
fdesetup status
```

## 5. Automatic login

Enable **automatic login** for the test user, and turn the screen lock off.

This is the mechanism that makes "keep the machine logged in" survive a
restart, and it does a second job that is easy to overlook: it unlocks the
login keychain. Without an unlocked login keychain, a harness CLI invoked over
SSH fails to reach stored credentials — the observed message is a locked-login-
keychain error from a command that works fine at the GUI Terminal.

Check:

```text
defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser
security show-keychain-info ~/Library/Keychains/login.keychain-db
```

The keychain check should report no timeout.

## 6. Sleep, disabled permanently

Disable system sleep, display sleep, and disk sleep — permanently, not for a
test interval:

```text
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
```

A permanent rig is not the same as a borrowed desk machine. The default sleep
timer on a freshly installed macOS can be as short as one minute, and while an
operator is connected over screen sharing that timer is held off, so the host
looks stable right up until the operator disconnects — at which point it sleeps
and drops off the private network. Restoring "normal sleep policy afterwards"
is the wrong instinct here: there is no afterwards for a permanent host.

Check:

```text
pmset -g | grep -E ' (sleep|displaysleep|disksleep)'
```

## 7. Command Line Tools

Install the Command Line Tools:

```text
xcode-select --install
```

Full Xcode is not needed. The Command Line Tools are, because Yoke is
git-native and because of a specific trap: on a freshly installed macOS,
`/usr/bin/git` is a shim that raises the developer-tools installation dialog
the first time it is invoked. Issued over SSH, that dialog appears on the
host's own screen — which nobody is watching — while the remote caller sees
only an unexplained error or a hang. An agent reads that as its own confusion
rather than as a machine-state precondition.

Install the tools during provisioning, before any capture or first mission, so
the dialog is already spent.

Check — this must return immediately, with no dialog raised on the host:

```text
git --version
```

## 8. Privacy grants for the terminal

In **System Settings → Privacy & Security**, grant the logged-in Terminal:

- **Screen Recording** — the runner captures the screen.
- **Accessibility** — the runner reads UI elements and injects keystrokes.
- **Automation**, for Terminal and System Events.

Accessibility is commonly missed because Screen Recording is the obvious one.
Without it, System Events UI-element reads fail with *"not allowed assistive
access (-25211)"*, and an agent that types cannot type.

Check — the read returns a count instead of `-25211`, and screen captures show
real window content:

```text
osascript -e 'tell application "System Events" to count processes'
```

Grants are independent durable machine state. They live partly in the system
privacy database outside any user home, so they survive resets and restores by
design — and a restore will not bring back a grant that was revoked. Assert
them separately; never infer them from a successful restore.

## 9. Harness applications and their CLIs

A controlled host must carry the harness applications installed **and signed
in**, because a mission exercises the machine the way a person would use it.

Install each harness's desktop application, then install its command-line
interface with that vendor's own installer. The CLI is generally not installed
by the application, and an application bundle may ship a different build than
the vendor's standalone installer produces; prefer the installer, so the host
matches what a real user's machine has.

Check each CLI reports **authenticated**, not merely present. A CLI that
resolves but is signed out fails at the first step of a mission:

```text
<harness-cli> --version
<harness-cli> <its login-status subcommand>
```

Run the authentication checks through the GUI Terminal bridge, not a bare SSH
shell — see the wrong-session boundary in the Pack README. An SSH session
cannot reach the login keychain, so a signed-in CLI can report itself signed
out there.

Whether the harness CLIs also resolve on the SSH `PATH` is an installer
concern rather than a provisioning one. Leave the host with exactly what each
vendor's installer produced.

## 10. Verify the capability — and know that the check is destructive

After provisioning, and after changing any setting, SSH key, or privacy grant,
run the project's readiness gate:

```text
yoke test-machine verify --project <project> --machine <resource-name>
```

**This command is destructive.** It performs the full host reset before
installing the current release — it is a readiness gate, not a reachability
probe. Do not reach for it to answer "can I see the machine?"; use a plain SSH
command for that. Run it deliberately, knowing the host's user state is reset.

That machine is not ready until its connectivity and terminal-control checks
pass. Register additional hosts as additional capability rows. Machine-backed
missions choose the first free row in name order, while each host retains its
own settings, verification receipt, and one-at-a-time lease.

## Acceptance set

Provisioning is complete when every line below is independently observable on
the host. Keep this set as the recurring assertion for the host, not as a
one-time checklist — several of these are durable machine state that a reset
or a restore does not re-establish.

```text
SSH reachable by the stable host name
full disk access granted for remote sessions
FileVault off
automatic login enabled
login keychain unlocked, no timeout
system, display, and disk sleep all disabled
Command Line Tools present; `git --version` returns with no dialog
Screen Recording granted to Terminal
Accessibility granted to Terminal (System Events read returns, no -25211)
screen captures show real window content, not wallpaper
every harness CLI reports authenticated
```

The screen-capture line deserves its own check rather than being folded into
the Screen Recording grant. A grant that is present but not effective produces
byte-identical wallpaper-only captures, and an agent choosing its next action
from a blind capture cannot proceed at all. Prove it by capturing two frames
across a window-state change: the digests must differ, and the frames must show
window content and the menu bar.

## Before capturing a restorable baseline

If the project keeps a captured baseline of this host's user state, capture it
only while the acceptance set above is green, and capture it after Command Line
Tools are installed — never before. Tools installed on first use raise their
dialog inside the first mission instead of during provisioning, which puts the
trap back exactly where a baseline was supposed to remove it.
