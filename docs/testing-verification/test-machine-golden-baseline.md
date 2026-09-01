# A fresh host is a user's machine, not an empty one

What the Test Mac's golden baseline is, how its probes sidecar declares which
programs it must carry signed in, and how to read a probe that fails. Companion
to
[`docs/testing-verification.md`](../testing-verification.md).

The registered `fresh-host` baseline restores the host's declared golden
baseline. Its target state is USER-EQUIVALENT, not bare: a real user arrives
with harness apps installed and signed in, so a machine stripped to nothing is
not a fresh host. Restoring a captured copy of the whole home, kept outside it,
is provably complete where enumerating residue never can be, and a host
declaring no `golden_baseline_path` cannot reach this baseline. Success is
gated on proof: no Yoke state, launcher, or tool file present, no Yoke tool
resolving in the login or SSH shell, every captured entry returned, and every
declared probe reporting its program signed in. The live `.ssh` directory and
`com.apple.TCC` privacy database survive the clear, and the restoring process
must hold Full Disk Access, which the operation asserts rather than assumes.

## What the restore cannot reach, the reset stops first

Restoring one home replaces everything that lives inside it, and a self-hosting
server walk puts most of its residue there: the bundle directory with its
owner-only `secrets/`, the minted API tokens, the local universe's Postgres
cluster, and — on a default macOS install — the container runtime's own data.

Two things are still outside the restore's reach, and the reset handles both
before it clears anything. The running server is one: containers, volumes, and
images can only be named by a daemon that is up, and a runtime whose data root
was moved outside the home would keep them whatever the restore does. So the
reset removes the bundle's own objects first, selecting them by the Compose
project label rather than by image name — the bundle shares its database image
with whatever else a user runs, and a name match would take theirs too. Images
are removed without force, because a refusal means another container still uses
the image, which makes it that workload's image rather than residue.

The live writer is the other. A container runtime backend keeps writing into
the very home the clear is replacing, and a local-universe Postgres server
names its own data directory on its command line while holding it open. Both
are stopped before the clear: the runtime application by name, the Postgres
server through the same process reap that already fails the reset when a Yoke
process survives it. A clear that races a live writer leaves the restore a
destination it cannot reconcile, which surfaces as a restore failure whose real
cause was never the restore.

The receipt reports what the teardown freed — containers, volumes, and images,
alongside the Compose project it selected — so a walk that left nothing behind
is distinguishable from one whose teardown never ran.

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

Structure is not liveness. A credential file comes back byte-identical and
still holds a token that expired while it sat in the snapshot, so the restore
proves the home is the captured one and the probes prove that home still
works.

The probes are declared in a sidecar document next to the golden itself —
`<golden_baseline_path>.probes` — because which programs must report themselves
signed in is a fact about one machine's baseline, not about every project Yoke
serves. The document is a bounded argv contract: an object with a `probes`
list, each entry naming the probe, an absolute-program argv, and an optional
`expect_output_contains` string.

They run through the Terminal.app GUI-session bridge rather than over SSH,
because an SSH session cannot reach the login keychain and a keychain-backed
program answering from the wrong session reports expired credentials whose
files are perfectly intact.

Probe output is summarized rather than recorded. A signed-in report names the
account it is signed in as, and that identity has no business in QA evidence,
so a failure is explained by a classified cause, reason, and recovery drawn
from fixed text — never by the output itself.

## The sidecar decides what must be signed in

**Capturing a golden means capturing it with every program named by that
golden's `.probes` sidecar already signed in.** The sidecar is the authority
for the required set; this guide does not fix that set in prose. A capture
taken while any declared program is signed out restores a host that Yoke
itself rejects as not user-equivalent, and the missions that depend on it park
on a machine no user has.

As an illustrative snapshot, the current Test Mac sidecar has three probes:
`claude auth status`, `codex login status`, and `cursor-agent status`. That
list can change with the baseline. The latter two commands report output
containing `Logged in` when authenticated, matching their current sidecar
expectations.

Recapturing a baseline with a new tool updates its probes in the same motion.
Adding a harness to the host without adding its probe leaves a signed-out
program the baseline never checks; adding a probe without recapturing leaves a
baseline that cannot pass. Do both, together.

## Reading a failed probe

A probe answers one of three ways, and the baseline keeps them apart because
their recoveries differ:

| Outcome | What happened | Recovery |
| --- | --- | --- |
| passed | the program reported itself signed in | none |
| `baseline_probe_failed` | the program ran and did not report itself signed in | recapture the golden with it signed in, or correct the probe argv or expectation |
| `baseline_probe_bridge_unavailable` | the bridge never delivered the probe, so the program said nothing | repair Terminal.app control on the host, then re-run `yoke test-machine verify --project <project> --machine <resource-name>` |

The third row is the one worth knowing about. The bridge reports its own
failure the way it reports a program's — a synthetic result carrying an exit
code, not a raised exception — so an undelivered probe and a signed-out program
look identical unless the result is classified. Read as a program verdict, an
undelivered probe sends an operator to recapture a whole home over a host
defect that would fail again on the next restore.

Each recorded probe row carries `cause`, `reason`, and `recovery` alongside its
exit code. Read those rather than inferring from the exit code: the bridge's
own failure sentinel is a number a program could also return.
