# The four things you can do to a test machine

`verify`, `reset`, `golden capture`, and `bridge diagnose` are commands every
Yoke user runs, not procedures each seat reinvents. Companion to
[`docs/testing-verification.md`](../testing-verification.md); the host-side
provisioning contract they assume ships in the
[`machine-qa` Pack](../packs/machine-qa).

Each takes the machine's one lease, refuses by name while another execution
holds it, and records its own receipt. The machine's page shows the last
receipt per operation, so what was last done to a box is readable without
asking the person who did it.

## Which implementation drives the host

Every machine declares a `host_kind` in its settings, and each kind implements
the same four operations behind one contract. `mac-ssh` — a macOS machine
reached over SSH and driven through its logged-in Terminal session — is the
registered kind. The kind is declared rather than inferred because the first
wrong guess runs a destructive restore against a machine it does not
understand; adding a kind is a new implementation plus a new enum value, and
changes no command, function id, or receipt shape.

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
describing what to change on the host:

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
