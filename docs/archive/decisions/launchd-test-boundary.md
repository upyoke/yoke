# A unique launchd label is not test isolation

## The problem this solves

Relay install is environment-qualified: the machine's canonical relay owns
`com.upyoke.relay`, and every other configured connection gets a suffixed
label derived from its config path. The suffix looks like isolation. It is
not, because the label was the only thing being varied — the job still
bootstrapped into the operator's real GUI login domain.

The bill arrived on one evening:

- Ninety-six leaked login items accumulated on one workstation, each pinned
  to a pytest temp directory that no longer existed.
- Eight of them registered during a single sweep, and macOS raised an *App
  Background Activity* notification for each one.
- The canonical relay was found unloaded twice, killing fleet launching both
  times (`no_eligible_relay: liveness_expired` refused three launches).

The third symptom is the one that explains the design. Installing a
per-environment relay retires an unpinned legacy job on the way in, and
"unpinned" is judged against the *installing* instance's config path. A test
config never matches, so the installer booted out `com.upyoke.relay` — the
live daemon serving the whole fleet — every time a test reached real
launchctl.

## Why the fix is not "stub it in the tests that do this"

The leaking call was not in a test. The onboard apply path spawns the relay
installer as a child process, so nothing the test monkeypatched was in scope
by the time launchctl ran, and the child resolved the operator's real home
rather than the temp home the test had built. Any per-test discipline would
have to be re-applied by every future test that walks any path that reaches
install — the shape that had already failed once.

## What is enforced instead

`yoke_core.tools.launchctl_boundary` is the one place Yoke may invoke
launchctl or resolve where a launch-agent plist lives. Under a test process
it never executes:

- With a sandbox exported (`YOKE_LAUNCHD_TEST_SANDBOX`, set per test by the
  repo-wide conftest), commands are appended to a journal and answered from
  it, and plists bound for the operator's real `~/Library/LaunchAgents` are
  written under the sandbox instead. A test that passes its own home is left
  alone — it was already writing somewhere disposable.
- With no sandbox, the call is refused by name and the refusal names the
  three ways out.
- The canonical relay label is refused even under the integration opt-in.
  The `real_launchd_agent` fixture buys a marked test a real launchd domain
  and boots out every label it registered in teardown; it never buys the
  machine's live daemon.

The environment variable carries the boundary across a process fork, which a
monkeypatch cannot do. That is the whole reason it is an environment
variable.

## Detection, because leaks predate the guard

`HC-session-relay-orphans` reads the per-environment relay plists and fails
on any whose pinned machine config no longer exists, listing the labels.
`yoke doctor run --quick --fix` unloads and deletes exactly those, leaves an
unreadable plist in place to be looked at, and never touches
`com.upyoke.relay`.
