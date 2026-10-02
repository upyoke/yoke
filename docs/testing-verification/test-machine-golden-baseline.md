# A fresh host is a user's machine, not an empty one

Keep browser authorization separate from this clean home golden. On Linux,
`yoke test-machine golden-capture --project P --machine NAME --component browser-profile`
seals only the stopped profile into a private sibling after desktop logout,
before any reset. It records `browser_profile_baseline_path` without changing
`golden_baseline_path`; no probe document is required for this component.
Ordinary resets never restore it. Exploratory browser missions install Yoke
first, then explicitly run `yoke qa browser setup --project P --profile-baseline
/absolute/sealed/snapshot --json` through the lease-routed host-command surface.
Terminal or machine-state host-control cases instead declare
`machine.browser-profile-restore` with canonical `project` and recorded
`baseline_path`. Read the commands' `--help` and the
Machine QA Pack's `browser-profile-baseline.md` for the complete recipe.
Prove sign-in by opening the app with the candidate daemon, never by a cookie
count or archive receipt. The profile archive stays on the private host.

What the Test Machine's golden baseline is, how its probes sidecar declares which
programs it must carry signed in, and how to read a probe that fails. Companion
to
[`docs/testing-verification.md`](../testing-verification.md); the command that
produces one, and what it refuses, is in
[`test-machine-operations.md`](test-machine-operations.md).

The registered `fresh-host` baseline restores the host's declared golden
baseline. Its target state is USER-EQUIVALENT, not bare: a real user arrives
with harness apps installed and signed in, so a machine stripped to nothing is
not a fresh host. Restoring a captured copy of the whole home, kept outside it,
is provably complete where enumerating residue never can be, and a host
declaring no `golden_baseline_path` cannot reach this baseline. Success is
gated on proof: no Yoke state, launcher, or tool file present, no Yoke tool
resolving in the login or SSH shell, every captured entry returned, and every
declared harness answering a real request. The live `.ssh` directory and
`com.apple.TCC` privacy database survive the clear, and the restoring process
must hold Full Disk Access, which the operation asserts rather than assumes.

Windows Test Machines restore only the non-root WSL2 Linux home through
Windows OpenSSH. Their golden path is a Linux path outside that home. Windows
SSH state and the WSL distro registration survive the restore; Linux probes
and absence checks run in the Linux home through `wsl.exe --cd ~ -e`.

## What the restore cannot reach, the reset stops first

Restoring one home replaces everything that lives inside it, and a self-hosting
server walk puts most of its residue there: the bundle directory with its
owner-only `secrets/`, the minted API tokens, the local universe's Postgres
cluster, and — on a default macOS install — the container runtime's own data.

Four things are still outside the restore's reach, and the reset handles each
before it reports the home restored. The running server is one: containers,
volumes, and images can only be named by a daemon that is up, and a runtime
whose data root was moved outside the home would keep them whatever the restore
does. So the reset removes the bundle's own objects first, selecting them by
the Compose project label rather than by image name — the bundle shares its
database image with whatever else a user runs, and a name match would take
theirs too. Images are removed without force, because a refusal means another
container still uses the image, which makes it that workload's image rather
than residue.

The live writer is the second. A container runtime backend keeps writing into
the very home the clear is replacing, and a local-universe Postgres server
names its own data directory on its command line while holding it open. Both
are stopped before the clear: the runtime application by name, the Postgres
server through the same process reap that already fails the reset when a Yoke
process survives it. A clear that races a live writer leaves the restore a
destination it cannot reconcile, which surfaces as a restore failure whose real
cause was never the restore.

Linux also stops the dedicated user's programs whose executable or arguments
name the home being restored, plus their descendants. This includes harness
daemons running from already-deleted executables: `/proc` still identifies their
home paths. Other users and unrelated system programs remain outside the reap.
PID start times protect reused process ids, and a fresh inventory must show no
home program before clearing starts. A respawning writer refuses the reset with
`linux_home_writers_stop_not_proved`, leaving the home intact. A deletion failure
names its top-level entry as `linux_golden_home_clear_failed`; stop its writer and
retry the sealed archive. Never recapture a mixed home after a failed restore.
System-installed packages remain outside this home-only baseline.

The third is product-owned temp files that never lived in the home. The
installer writes `/tmp/yoke-install`; the verifier already requires that path
absent, and the clear removes it from the same declared absence roster rather
than discovering residue by glob. A live installer process whose command line
still names the path refuses the clear instead of deleting under it. A leftover
that survives names the exact path plus the recovery step on the receipt
(`absent_state`). Walker scratch under `/tmp` that is not on that roster —
lease-scoped token files, `mktemp` names — is the walker's own teardown
contract, not a reset enumeration. The home-relative walker client token under
`.yoke/secrets/` is already inside a directory the restore requires absent.

The receipt reports what the teardown freed — containers, volumes, and images,
alongside the Compose project it selected — so a walk that left nothing behind
is distinguishable from one whose teardown never ran.

The fourth is launchd's own job registry, which no home restore can reach. A
Yoke relay LaunchAgent loaded under the test account survives the clear
because launchd — not the home — holds the record of it, and a job left
loaded rewrites the state directory the clear just emptied the moment it next
runs: the home comes back clean and the verifier still finds Yoke state the
service recreated seconds later. So the reset boots the account's relay out
before the reap and the clear run, addressing it by the relay's own label
naming rather than an observed instance, and leaves every other launchd job
on the host alone. A host with no relay loaded passes cleanly; one still
loaded after its bootout stops the reset with the home intact and names the
label plus its recovery (`relay_service_state`).

## Reading a stopped restore

A restore that stops names the captured entries it could not return, and that
report rides the failure into the receipt as `restore_state`. Entry names are
reduced to letters, digits, dots, dashes, and underscores before they travel,
because the program's output contract is closed and a name carrying a space or
a quote would reopen it.

Read those names first. Without them the receipt carries only the phase, and
diagnosis means reproducing a multi-gigabyte restore on the host just to watch
where it stopped — which is what one operator did before the report existed.

## The probes live beside the golden

Structure is not liveness. A captured credential can expire or lose its
refresh token while it sits in the snapshot. The restore proves captured
settings and history, and the probes prove that the home still works.

Linux reset first refuses a live XFCE session, an active graphical login, or
a mounted `thinclient_drives`: `linux_reset_desktop_logged_in` says
“operator is logged in to the desktop; log out first”. An empty, unmounted
`thinclient_drives` directory left after logout is safe to clear. These checks
precede service cleanup, process signals and home changes.

When the sealed probes declare Claude, reset makes one tiny real request
with the current login before teardown. Authentication failure names
`linux_reset_claude_auth_failed` and tells the operator to sign in again;
network, timeout and other request failures name their distinct causes and
require repair and retry. The receipt includes the diagnosed CLI error line,
with token-shaped material redacted. No failed request falls back to archived
credentials.

After a passing request, reset copies `~/.claude/.credentials.json` as opaque
bytes into an owner-only stash outside the home. It restores those post-request
bytes with the same owner and mode 0600, even after a midway failure, then
removes the stash. A failed credential restore names the private stash and
recovery step; retain it until restoration succeeds. Claude settings and
history remain golden-owned. Machines without a declared Claude probe keep
golden credential behavior. This applies to Linux homes (including WSL);
macOS Keychain and Codex/Cursor credential preservation are outside this path.

The probes are declared in a sidecar document next to the golden itself —
`<golden_baseline_path>.probes` — because which programs must be
signed in is a fact about one machine's baseline, not about every project Yoke
serves. The document is a bounded argv contract: an object with a `probes`
list, each entry naming the probe, an absolute-program argv, and an optional
`expect_output_contains` string.

On macOS they run through the Terminal.app GUI-session bridge,
because an SSH session cannot reach the login keychain and a keychain-backed
program answering from the wrong session reports expired credentials whose
files are perfectly intact. Linux and WSL run them in the SSH user's Linux session.

Probe output is summarized rather than recorded. A signed-in report names the
account it is signed in as, and that identity has no business in QA evidence,
so a failure is explained by a classified cause, reason, and recovery drawn
from fixed text. Linux reset admission additionally records only the diagnosed
Claude error line, with token-shaped material redacted; successful account
output and credential contents are never recorded.

## The sidecar decides what must be signed in

**Capturing a golden means capturing it with every program named by that
golden's `.probes` sidecar already signed in.** The sidecar is the authority
for the required set; this guide does not fix that set in prose. A capture
taken while any declared program is signed out restores a host that Yoke
itself rejects as not user-equivalent, and the missions that depend on it park
on a machine no user has.

For an absolute executable named `claude`, `codex`, or `cursor-agent`, the
runner replaces the declared argv and output expectation with a tiny native
request: “Reply exactly OK. Do not use any tools.” This applies to already
sealed sidecars too: login-status output never proves that a credential can
refresh or that a request succeeds. Other CLI and service probes keep their
declared argv and expectation.

The request uses native noninteractive output, limits tools where the CLI
allows it, and requires a successful completion containing `OK` with no
tool-call events. Claude uses safe mode to preserve OAuth/keychain authentication
while suppressing customization; its built-in tools and MCP configuration are disabled;
Codex ignores user configuration, disables its shell tool, and runs read-only;
Cursor runs in Ask mode. Codex and Cursor use `/tmp` as their workspace so
project instructions cannot turn the probe into project work. No permission
bypass or harness account data is recorded. The native CLI flag contracts are
documented in the [Claude reference](https://code.claude.com/docs/en/cli-reference),
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
and [Cursor output format](https://cursor.com/docs/cli/reference/output-format).

Recapturing a baseline with a new tool updates its probes in the same motion.
Adding a harness to the host without adding its probe leaves a signed-out
program the baseline never checks; adding a probe without recapturing leaves a
baseline that cannot pass. Do both, together — which is what
`yoke test-machine golden-capture --probes-file <file>` does in one operation:
it runs the document's probes, refuses unless every one passes, captures the
home, and seals that same document beside the new golden with its digest
recorded in the manifest.

## Reading a failed probe

A probe answers one of three ways, and the baseline keeps them apart because
their recoveries differ:

| Outcome | What happened | Recovery |
| --- | --- | --- |
| passed | the harness answered the real request, or another declared probe passed | none |
| `baseline_probe_failed` | a harness request or another declared probe failed | for a harness, re-sign-in with the exact absolute command in `reason`, then retry; for another probe, correct its argv or expectation |
| `baseline_probe_bridge_unavailable` | the bridge never delivered the probe, so the program said nothing | run `yoke test-machine bridge-diagnose --project <project> --machine <resource-name>`; it names which bridge capability broke and what to change |

The third row is the one worth knowing about. The bridge reports its own
failure the way it reports a program's — a synthetic result carrying an exit
code, not a raised exception — so an undelivered probe and a signed-out program
look identical unless the result is classified. Read as a program verdict, an
undelivered probe sends an operator to recapture a whole home over a host
defect that would fail again on the next restore.

Each recorded probe row carries `cause`, `reason`, and `recovery` alongside its
exit code. Read those rather than inferring from the exit code: the bridge's
own failure sentinel is a number a program could also return.

Linux reset removes Yoke-owned user service definitions and links, including
`com.upyoke.*.service`, from the user manager's reported unit search paths.
It stops loaded units even when their FragmentPath was deleted, reloads the
manager, then proves loaded units and definitions absent. It checks linger
without disabling unrelated user services. A foreign-owned definition refuses
for administrator repair; service absence is never inferred from a missing file.
A home archive containing a Yoke service definition refuses before clearing.
