# Provisioning and restoring a controlled macOS QA host

## Context

Machine QA drives a real macOS machine rather than a container: it opens
Terminal windows, reads the screen, injects keystrokes, and reaches the host
over SSH. That makes the machine's own state part of the test fixture, and it
makes returning the machine to a known state a genuine engineering problem
rather than a `docker run`.

Two questions had to be answered together. First, how a host is prepared so it
can be driven at all. Second, how it is returned to that prepared state between
runs, given that every run installs software, signs in to things, and leaves
residue behind.

The first attempt at the second question was to enumerate what a run leaves
behind and remove it. The reasoning below is written down because each
constraint it produced looks, from a distance, like something a later
maintainer could simplify away — and each one was learned by watching the
simpler version fail.

## Decision

### A restorable baseline, not an enumerated cleanup

Returning the host to a known state means restoring a captured baseline
wholesale, not removing the things a run is believed to have added.

Enumeration cannot be proven complete. It removes the locations someone thought
of, and it reports success either way. The failure is silent by construction:
the cleanup exits zero, the machine looks plausible, and the next run starts
from a state nobody can name. Restoring a captured baseline inverts the burden —
what the machine contains afterwards is whatever was captured, and that is a
fact about an artifact rather than a claim about someone's memory.

This was tested directly. A careful, evidence-driven enumeration pass removed
the tool's own residue successfully and still failed its actual goal: it deleted
the configuration files and application-support directories it knew about, and
missed preference property lists, containers and group containers, web-storage
and cookie stores where applications park sessions, per-bundle caches, saved
application state, logs, and login-keychain items. One application reporting
itself signed out was read as evidence that all of them were. The method was the
defect, not the coverage — and the same method applied to the tool's own state
would have failed the same way with less visible symptoms.

The one place enumeration is legitimate is the supervised, one-time construction
of the baseline itself, where contents are verified by searching the machine
rather than by recalling what was installed. Every run after that is a restore.

### The user home is the unit of capture and restore

The baseline captures and restores one user's home directory.

It is chosen because it is exactly the blast radius of the reset it replaces:
the reset contract already refuses any target that escapes the test user's home,
so the home is the largest thing a run can damage and the smallest thing that
must therefore be restorable. Everything inside it is owned by the test user, so
capture and restore need no administrative privilege — which matters because the
established contract is that host baselines run as the test user and never
invoke `sudo`, and a machine may have no password-less `sudo` available at all.

Whole-volume mechanisms were considered and rejected on the same constraint.
Filesystem snapshots are thinned automatically after about a day, so they cannot
carry a durable baseline. Reverting or imaging a boot volume needs it unmounted,
which needs a recovery boot, which is not something a headless rig can be driven
through remotely. A home-directory replacement is durable, checksummable,
re-runnable, and needs no reboot.

The baseline is stored outside the home it restores. Anything the reset can
reach is not a safe place to keep the thing that repairs it.

### The privacy database is excluded from the restore

The macOS privacy database holding screen-recording and accessibility grants is
captured but never written back, and the delete phase preserves the live copy.

Those grants can only be established by a person clicking in a settings pane.
They are also system-protected. Restoring a captured copy over the live one
would replace present grants with whatever was true at capture time, and no
scripted run could repair the result. Preserving the live database across
restores is therefore the correct design and not a workaround: permissions are
independent durable machine state with their own lifetime.

The consequence has to be stated plainly, because it is the kind of thing that
gets forgotten: **the baseline does not guarantee the grants.** Revoke one and
restoring the baseline will not bring it back. They need their own assertions,
and they must never be inferred from a successful restore.

The same reasoning applies to the SSH material that carries the restore command
itself. The delete phase preserves it, because a sweep that destroys its own
control channel leaves the host unreachable in the window before the restore
lands — observed live, and recovered only by a person walking up to the machine.
Some state must survive the sweep precisely because the sweep depends on it.

Preserving paths at different depths makes the delete and restore loops
asymmetric if written carelessly. Each must descend exactly as far as the
preserved path's ancestor chain requires. Flattening either into a single
recursive call is the bug the symmetry exists to prevent.

### Command Line Tools are installed before capture, never on first use

The developer command line tools are part of the provisioned host and are
installed before any baseline is captured.

On a freshly installed macOS, `/usr/bin/git` is a shim that raises a graphical
installation dialog the first time it is invoked. Issued over SSH, that dialog
appears on the host's own screen — which nobody is watching — while the remote
caller receives an unexplained error or simply hangs. An agent choosing its next
action reads that as its own confusion rather than as a missing precondition,
and a scripted run blocks on a modal indefinitely.

Installing the tools during provisioning spends the dialog once, in front of the
person who can dismiss it. Deferring it to first use moves a machine-state
problem into the middle of a test run, where it is at its most expensive to
diagnose and least likely to be diagnosed correctly.

The general rule this instance illustrates: anything whose first invocation
prompts a human belongs in provisioning, not in the run.

### Window-server and keychain work routes through the GUI bridge

Commands that touch the window server or the login keychain execute through the
logged-in graphical Terminal session, not through a bare SSH shell.

An SSH session is not the logged-in graphical session, and macOS enforces that
distinction. Screen capture fails outright with an inability to create an image
from the display. The login keychain refuses with a locked-keychain or
no-user-interaction error, so a signed-in tool reports itself signed out. These
read as broken credentials or a broken tool; they are neither. They are all one
signal, which is that the command reached the wrong session.

This is also why automatic login belongs in the provisioning contract. It is not
merely convenience for screenshots: it is what produces a logged-in graphical
session for the bridge to reach, and what leaves the login keychain unlocked so
credentials stored in it are reachable at all.

Full disk access is the other half. The process performing a capture or restore
must hold that grant — and the invariant is the *grant*, not the channel. SSH
holds it by default on a host provisioned this way, so "run it over SSH" appears
to work as a rule and is wrong: it passes unchanged on a host where the grant was
later revoked, which is the same silent failure wearing a different mask. Assert
the grant.

The same attribution rule governs interactive control. Remote Login commands
that send AppleEvents or synthesize keystrokes are attributed by macOS to
`/usr/libexec/sshd-keygen-wrapper`, not to Terminal.app merely because Terminal
is the visible target. The wrapper therefore needs its own Accessibility and
Automation grants. Terminal's Screen Recording grant remains separate for
captures performed inside the GUI bridge. Provisioning must probe each real
path and request the consent dialog for the process that failed; routing an
action through another process to avoid the dialog would make the fixture less
representative and leave the original path broken.

The failure it prevents is precise. Without the grant, the identical restore
command skipped 8,389 entries across protected library subtrees — containers,
metadata, browser and messaging state — and reported success. It looked clean
because its error output had been discarded. **Never suppress the restore's
error stream:** capture it, count it, and treat a non-empty log as a failed
restore. A restore that cannot prove it copied everything reintroduces, at the
last step, exactly the unprovable-completeness problem the design exists to
escape.

Two smaller mechanics belong with it, both learned by failing them. Enumerate
entries with `find` rather than shell globs: an interactive shell treats `!` in a
glob as history expansion, and a shell that aborts on an unmatched glob kills the
whole command when a directory happens to contain no dotfiles. And ignore
permission-denied errors from the delete phase specifically: a standard access
control list forbids removing certain home directories while permitting their
contents to be cleared, so a correct run reports those errors, and an
implementation that aborts on the delete phase's exit status fails on success.
That tolerance applies to the delete phase only — never to the restore.

Restore cannot assume that clear made every destination absent. Read-only cache
trees can retain children, and macOS home directories such as `Public` and
`Library/Audio` carry delete-denying ACLs. Clone-copy then refuses an existing
file, while merging a protected directory can duplicate its ACL on every reset.
For each non-preserved captured entry, reset therefore removes ACLs from the
live destination, makes its directories owner-writable, deletes it, and permits
only an empty, type-compatible protected directory to remain before copying the
captured metadata back. The golden is never made writable or modified. This is
safe precisely because the symmetric level walk never hands `.ssh` or the TCC
database to destination preparation.

The same ownership boundary applies at capture. Every entry in the dedicated
test home must belong to the test user before sealing. A root-owned preference
file is not harmless noise: the test user cannot reliably clear or restore it,
so excluding it would make the whole-home completeness claim false. Repair the
owner inside the test home, re-run the ownership check, then capture.
Apply the golden's final mode before generating its manifest. A manifest made
first records a transient mode and fails every later integrity check even when
all captured content and digests are unchanged.

### The capability stores a stable host name, not an address

The saved capability identifies the host by a stable private-network name.

A rebuilt host registers as a new node and is assigned a new address. An address
stored in the capability therefore keeps working right up until the machine is
rebuilt, and then fails in a way that presents as an unreachable capability
rather than as a stale setting — the reader sees a connection failure, not a
configuration error, and looks in the wrong place.

The name has one operational requirement: when rebuilding a host, delete its old
node registration before the rebuilt machine authenticates, or the name is
already taken and the new node registers under a suffixed variant.

### Yoke is never inside the baseline

The baseline contains no part of Yoke, and installing Yoke is part of every run
rather than part of the machine.

The distinction is provenance. State a harness's own installer creates is user
state and belongs in the baseline; state Yoke creates is not. Yoke's own
dependencies are Yoke's to install, not the machine's to carry. A baseline with
Yoke pre-seeded turns an installation test into a rehearsal of one, because the
thing under test is already present before the test begins.

The assertion that makes the baseline trustworthy is exactly this: prove no Yoke
artifact exists anywhere in the home *before* sealing it. That assertion is only
meaningful at capture time, because after the first run the machine has Yoke on
it by design.

## Consequences

- Host provisioning is a general capability concern and lives in the
  `machine-qa` Pack, at `docs/packs/machine-qa/host-provisioning.md`. Projects
  keep only their own host's specifics. A second copy of the procedure is how
  the previous one went stale and, in one step, actively wrong.
- Provisioning is not complete at "installed and signed in". Its acceptance set
  includes reachability by stable name, the full disk access grant, encryption
  off, automatic login, an unlocked login keychain, sleep disabled permanently,
  developer tools present, both privacy grants, authenticated harness
  interfaces, and a proof that screen captures show real window content.
- That last check is separate from the screen-recording grant on purpose. A
  grant that is present but not effective yields identical wallpaper-only
  captures, and an agent choosing its next action from a blind capture cannot
  proceed at all — while the failure presents as agent confusion. Prove it with
  two frames across a window-state change: the digests must differ.
- Permission grants are asserted independently, every time. They are durable
  machine state that neither a reset nor a restore re-establishes.
- Privacy grants are recorded against the process macOS actually attributes as
  the controller. Remote Login and GUI Terminal are separate paths and neither
  one's grants prove the other can control or capture the desktop.
- The readiness gate that verifies a test-machine capability performs the full
  destructive host reset before installing the current release. Every surface
  that teaches the command says so, because reaching for it as a reachability
  probe wipes the host.
- Adding a tool to the baseline later never requires rebuilding the machine:
  restore, install, re-verify the acceptance set, and re-seal. Capture is a
  filesystem clone and costs seconds and near-zero space. Only the initial
  erase is irreversible, which is why deferring a decision about baseline
  contents is cheap and rushing one is not.
- Anything that must survive a machine rebuild has to leave the machine, not
  merely leave the home directory. Files moved outside the home to keep them
  out of the baseline were still lost with the volume.
