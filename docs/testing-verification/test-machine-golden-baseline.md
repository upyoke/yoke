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
| `baseline_probe_bridge_unavailable` | the bridge never delivered the probe, so the program said nothing | repair Terminal.app control on the host, then re-run `yoke test-machine verify` |

The third row is the one worth knowing about. The bridge reports its own
failure the way it reports a program's — a synthetic result carrying an exit
code, not a raised exception — so an undelivered probe and a signed-out program
look identical unless the result is classified. Read as a program verdict, an
undelivered probe sends an operator to recapture a whole home over a host
defect that would fail again on the next restore.

Each recorded probe row carries `cause`, `reason`, and `recovery` alongside its
exit code. Read those rather than inferring from the exit code: the bridge's
own failure sentinel is a number a program could also return.
