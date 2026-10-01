# What you can do to a test machine

`verify`, `reset`, `golden capture`, `bridge diagnose`, `exec`, and `desktop-access` are
commands every Yoke user runs, not procedures each seat reinvents. Companion to
[`docs/testing-verification.md`](../testing-verification.md); the host-side
provisioning contract they assume ships in the
[`machine-qa` Pack](../packs/machine-qa).

The first four each take the machine's one lease, refuse by name while
another execution holds it, and record their own receipt. The machine's page shows the last
receipt per operation, so what was last done to a box is readable without
asking the person who did it.

## desktop-access — connect to a registered desktop

```text
yoke test-machine desktop-access --project P --machine NAME
```

Run this on the workstation holding the capability secrets. It authorizes the
registered route, refuses another session's machine lease, checks the RDP/VNC
handshake, and prints only `address`, `user`, and `password_file`. Open that
address in your RDP or Screen Sharing client, and use the desktop user and
password from the private mode-600 file under `/tmp`. No password goes through
the control plane, events, operation receipts, or command output.

Settings declare `desktop_route` (`direct` or `ssh-forward`),
`desktop_protocol` (`rdp` or `vnc`), `desktop_port` (1–65535), and
`desktop_user` together. Optional `desktop_host` names the desktop endpoint:
it defaults to the registered host for direct access, or `127.0.0.1` on the
SSH host for forwarding. `cloud_instance_id` records an EC2 id when present.
Desktop credentials stay separate from the SSH login, including Windows RDP
as Administrator when SSH enters WSL2. Save routes with
`yoke test-machine settings-replace`; read its `--help` for the CAS token.

Import each password from a private file, never from a literal argument:

```text
yoke projects capability secret set --project P --cap-type test-machine:NAME \
  --key desktop_password --value-file /tmp/NAME-desktop-password.txt
```

`--value-stdin` also works. Passwords live in the existing capability secret
store, keyed by machine, beside the shared `test-machine.ssh_private_key`.
`test-machine get/list` reports presence on the executing workstation and
the route, never a secret value. Missing passwords refuse with
`desktop_password_missing` and the import command.

SSH forwarding chooses a free loopback port, uses the capability SSH key and
Yoke's pinned host keys, and keeps its listener open after the command exits.
The control socket is `PASSWORD_FILE.ssh`. Close the forward after use with
`ssh -F /dev/null -S PASSWORD_FILE.ssh -O exit SSH_USER@SSH_HOST`, using the
registered SSH host/user, then remove the temporary password copy. A failed
open removes the copy and closes its tunnel. This command changes no host
password, firewall, desktop service, or auto-login setting.

## Which implementation drives the host

Every Test Machine declares `os=macos|linux|windows`. All are persistent SSH hosts;
`os` selects restore, terminal bridge and verification behavior. macOS uses
its logged-in Terminal.app session; Linux uses a non-root user and tmux.
Windows uses Windows OpenSSH into the SSH account's default WSL2 distro,
reusing Linux home archives and tmux under a non-root Linux user. Golden
paths name Linux paths; Windows state and distro registration survive reset.
Ad hoc `exec` also enters WSL, preserving the Linux command's exit status.
Provisioning details ship in the machine-qa Pack's Windows guide.
Unsupported values refuse with `test_machine_os_unsupported` and list the
supported values. Settings without `os` refuse with
`test_machine_os_serving_floor_required`: deploy the next-release serving
build and converge stored settings before running the OS-aware client.

A Test Machine capability owns settings, credentials, QA leases and receipts.
A registered capacity machine owns agent-launch capacity and relay identity.
One physical host may have both records; the capacity registry does not grant
QA readiness. Do not launch ordinary work into the dedicated test user's home
while a reset or QA lease holds it. A reset owns that home, so use a different
user for launch capacity. Machine detail links matching hostnames to capability
commands; it does not merge either identity or lease.

Linux golden directories contain a private home archive and a manifest binding
its SHA-256 digest to the test user/home. They stay outside the home. Capture
omits Unix sockets and symlinks that resolve to sockets or outside the captured
home, regardless of filename; regular files and safe links named `.sock` stay.
Restore validates identity, digest and every archive entry before clearing the home,
stops that user's home-resident programs and descendants (including deleted
harness executables), preserves `.ssh`, compares restored file digests, and proves Yoke state and
launcher paths absent on SSH and login shells. Declared probes then check
CLI authentication, credential files and relevant user services over SSH.
Surviving or respawning home programs refuse before clearing with
`linux_home_writers_stop_not_proved`. A clear failure reports
`linux_golden_home_clear_failed` and `refused_entry`: stop the writer and retry
the sealed archive; never capture the mixed home. OS packages are not restored.
Linux terminal evidence is a tmux transcript. Screenshot or GUI-session cases
refuse with `headless_linux_screenshot_unavailable` and a designed deferral;
use a macOS Test Machine for that proof. Browser-approval recipes likewise
name `headless_linux_browser_approval_unavailable`.

## verify — the readiness gate, and what it leaves behind

```text
yoke test-machine verify --project <project> --machine <resource-name>
```

Verification proves the transport, the Terminal bridge, and BOTH registered
baselines in order. Because it reaches them in order, the box it hands back is
whatever the last one leaves: `shell-preconfigured` ends with the current Yoke
launcher installed on both shell surfaces. **That is not a fresh host**, and
the receipt says so in words rather than leaving it to be inferred from a
baseline name. Reset afterwards when you need the machine to look untouched.

The receipt also reports each route separately under `surfaces`: `ssh` (the
transport every command, reset, and machine assertion rides) and
`terminal_bridge` (the Terminal.app route GUI captures ride), each `passed`,
`failed`, or `not_run`. A failed bridge leaves the overall status `error`, but
`surfaces.ssh` still reads `passed`, so the machine is not mistaken for
unreachable; the failed surface carries its own recovery.
`yoke test-machine get` shows the same map for the last verification.

## reset — one baseline, and stop

```text
yoke test-machine reset --project <project> --machine <resource-name> \
  [--baseline fresh-host|shell-preconfigured]
```

`fresh-host` is the default, because it is the state an operator asks for when
they say "give me the box back". The receipt carries the restore's own
evidence: what was restored, what is now absent, and the resulting shell PATH
state. A reset does not change whether the machine is verified — a fresh box is
still a proven one — so it records beside the verification row rather than
into it.

## golden capture — producing a baseline a reset can restore

```text
yoke test-machine golden-capture --project <project> --machine <resource-name> \
  [--destination <abs-path>] [--probes-file <file>]
```

By default the capture writes a new dated directory beside the machine's
current golden and records that path on the machine once it succeeds, so a
failed capture never destroys the baseline it was taken beside and a successful
one never silently retires a directory another host may still restore from.
Pass `--destination` for a machine's first golden, or to place one
deliberately. Pass `--probes-file` to seal a new probe document; without it the
capture carries forward the document sealed beside the current golden.

It refuses rather than producing a baseline nothing can restore:

| Refusal | What it found | What to do |
| --- | --- | --- |
| `golden_capture_yoke_residue` | Yoke state at a named path inside the home | Reset the host first. Capturing it bakes Yoke into the baseline every later reset restores, and the reset then verifies that same state absent — so the machine could never pass again |
| `golden_capture_foreign_owner` | An entry inside the test home owned by another account | Repair its owner; the test user cannot clear or restore what it does not own |
| `golden_capture_destination_occupied` | Something already at the destination | Choose a new destination |
| `baseline_probes_not_declared` | No probe document to seal | Pass `--probes-file`; a golden with no probes is one no reset accepts |
| `baseline_probe_failed` | A declared program reported itself signed out | Sign it in, or correct the probe's argv or expectation |

What it writes beside the golden directory: a `.manifest` recording when it was
captured, from which home and user, how many top-level entries and kilobytes,
and the digest of the probes sealed with it; and a `.probes` sidecar holding
that document. Both are read-only, and so is the golden directory object — but
the captured files keep exactly the modes and ACLs they had, because the
restore restores modes from the golden and rewriting them here would make every
restored home wrong.

## Browser profile capture — separate from the clean home

For a separately sealed Linux browser profile, use
`yoke test-machine golden-capture --project P --machine NAME --component browser-profile --json`.
Read its `--help` first. Capture after desktop logout and browser-daemon stop,
before any reset; no probes file is required. The same host lease and receipt
bind a new private sibling archive to home, UID and project. Success records
`browser_profile_baseline_path`, preserving the clean `golden_baseline_path`.
This component refuses active writers, occupied destinations and unsafe
entries. The profile remains outside all ordinary baseline restoration;
exploratory missions explicitly run `yoke qa browser setup --project P
--profile-baseline /absolute/sealed/snapshot --json` through the lease-routed
host-command surface after installing the candidate. It restores before daemon
startup; default setup and dry-run never restore. Terminal or machine-state
host-control cases instead declare `machine.browser-profile-restore` setup.
A sealed receipt
does not prove sign-in: use the candidate daemon to open the actual app.
See the Machine QA Pack's `browser-profile-baseline.md` for the full recipe.

## bridge diagnose — which capability broke, and why

```text
yoke test-machine bridge-diagnose --project <project> --machine <resource-name>
```

Verification answers one question — can the bridge do its job — and stops at
the first failure. That is right for a gate and wrong for a person standing in
front of a machine that will not cooperate. Diagnosis runs the same
capabilities one at a time, in an order where each answer is only meaningful
once the one before it worked:

```text
ssh_transport · console_session · system_events_control · terminal_app_control
secure_keyboard_entry · display_frame · window_launch · window_focus
keystroke_delivery · window_transcript · window_screen_capture
```

A capability whose precondition failed is reported as **not run**, naming the
check that stopped it, rather than as a second failure — one missing privacy
grant used to produce five red lines that each read like an independent
problem. Every failing row carries the condition's name and the sentence
describing what to change on the host. The console check reads the lock flag
inside macOS's `IOConsoleUsers` root property, including compact `=Yes` output.
A locked console reports `terminal_display_locked`: unlock the Mac before
retrying. The `window_launch` row retains the osascript exit code, stdout, and
stderr, so a Terminal AppleScript failure carries its cause:

| Condition | What to change |
| --- | --- |
| `terminal_ssh_unavailable` | Remote Login for the automation user, and this machine's `ssh_private_key` capability secret |
| `terminal_console_user_mismatch` | Log the graphical session in as the automation user |
| `terminal_display_locked` | Unlock the screen; disable screen saver and display sleep |
| `terminal_system_events_unavailable` | Accessibility, and Automation for System Events, for `/usr/libexec/sshd-keygen-wrapper` (-25211 names the first, -1743 the second) |
| `terminal_automation_unavailable` | Automation for Terminal, for the same Remote Login helper |
| `terminal_secure_keyboard_entry_on` | Turn Secure Keyboard Entry off in Terminal's menu; while it is on macOS discards every synthetic keystroke |
| `terminal_display_frame_unavailable` | Attach a display and log the graphical session in |
| `terminal_window_focus_timeout` | Something else held focus, or the host is too loaded; the row records the frontmost process, the load average, and the wait it allowed |
| `terminal_keystroke_undelivered` | The window was frontmost and macOS refused the event: check Accessibility and Secure Keyboard Entry |
| `terminal_transcript_timeout` | Keys were delivered and the window never showed them inside the wait; the row records the load and the wait it sized |
| `terminal_window_off_screen` | The window would not stay inside the display's visible frame |
| `terminal_screen_recording_required` | Screen Recording for Terminal.app; captures currently hold wallpaper |
| `terminal_screen_capture_failed` | Read the recorded capture command, exit code, and stderr in the row |

## exec — one ad hoc command, outside any QA case

```text
yoke test-machine exec --project <project> --machine <resource-name> -- <command...>
```

Runs one command on the host as the capability's `user` at its `host`, with
this machine's own ssh-agent identity, and exits with the command's status.
Stdout and stderr stream live as they arrive. Only the last 64 KiB of each
stream is retained for failure diagnosis, so long commands do not accumulate
their full output in memory.
The words after `--` reach the remote login shell exactly as `ssh` sends
them, so `-- 'ls ~/.yoke && cat ~/.zshrc'` expands on the host. It never
reads `~/.ssh` — a relay-launched session is denied that directory — so it
skips the user's SSH config and pins host keys in
`~/.yoke/test-machine/known_hosts`. It takes no lease and records no receipt,
but refuses with `test_machine_leased` while another session holds the host;
a QA mission walker uses `yoke qa mission host-command` instead.
On macOS, keychain-backed harness CLIs (`claude`, `cursor-agent`) run through
`yoke qa mission host-command --execution-id ID --requirement-id N --gui-session -- ARGV...`
under an awaiting mission's retained lease; verify sign-in there first when SSH
reports `macos_login_keychain_context_unavailable`, an SSH session-context
failure rather than a sign-in diagnosis.

| Refusal | What to do |
| --- | --- |
| `test_machine_ssh_agent_unavailable` | Run from a shell whose `SSH_AUTH_SOCK` reaches an agent holding a key the host authorizes (`ssh-add -l`) |
| `test_machine_ssh_failed` | Check reachability and the agent's key; after a host rebuild, remove the stale pin with the `ssh-keygen -R <host> -f ~/.yoke/test-machine/known_hosts` the refusal prints |
| `test_machine_leased` | Wait for the named session's lease to release, or ask it to run the command |

`yoke machine detail` on the host's own relay machine lists the capability
under `test_machines` with this exact command, so the route is found from
either side.

## Why the bridge waits, and why the waits are not fixed

Asking Terminal to activate a window and typing in the same breath is a race a
loaded Mac loses. `activate` returns as soon as the request is made; on a busy
host the new window is not frontmost for seconds afterwards, and the keystrokes
land in whatever window still is. The bridge therefore polls until the target
window is the frontmost window of the frontmost application before typing.

The waits are sized by the host's own one-minute load average rather than
fixed, because the delay between asking for focus and holding it is exactly
what the load makes longer, and a wait tuned for an idle Mac expires on a
merely busy one. Every timeout reports the load that sized it, so it reads as
"this long, at this load" rather than as a missing privacy grant — which is how
one focus race was diagnosed as permissions for a day.

Linux reset removes Yoke-owned user service definitions and links, including
`com.upyoke.*.service`, from the user manager's reported unit search paths.
It stops loaded units even when their FragmentPath was deleted, reloads the
manager, then proves loaded units and definitions absent. It checks linger
without disabling unrelated user services. A foreign-owned definition refuses
for administrator repair; service absence is never inferred from a missing file.
A home archive containing a Yoke service definition refuses before clearing.
