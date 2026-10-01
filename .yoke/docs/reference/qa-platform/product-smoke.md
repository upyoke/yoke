# Manual product smoke on Linux and macOS

For signed-in native Claude, Codex and Cursor sessions on persistent test
machines, use [Real harness Machine QA](real-harness.md). That manual plan
complements the disposable-runner hook replay below.

The Yoke project plan `product-smoke` has one `command-ci` case bound to
`product-smoke.yml`. Its manually dispatched matrix runs the complete smoke on
all three GitHub-hosted disposable runners. Nothing schedules it or attaches it to
changes, pull requests, merges, or deployment gates.

The jobs declare Ubuntu 24.04 x86_64 (`ubuntu-latest`), Ubuntu 24.04 arm64
(`ubuntu-24.04-arm`), and macOS 26 arm64 (`macos-latest`). These labels follow
[GitHub's runner image catalog](https://github.com/actions/runner-images) and
[ARM runner catalog](https://github.com/actions/partner-runner-images). Linux's
`aarch64` machine name is reported as `arm64` to match the matrix declaration.
The smoke verifies the actual OS and architecture first; a label migration
refuses with `runner_identity_mismatch` until its declaration is reviewed.

The Ubuntu job removes one Chromium library package from its disposable runner
before onboarding. It then requires captured proof that onboarding installed
missing libraries through passwordless sudo and validated them afterwards;
"already present" cannot pass this branch check. The fixture never runs on the
operator machine. macOS retains its ordinary browser setup path.

Each job builds and installs the tree's product wheels into a fresh environment,
onboards a Git project non-interactively into a fresh local universe with GitHub
adoption disabled, and replays native SessionStart and allowed/denied shell
payloads through the exact commands in its installed `.claude/settings.json`,
`.codex/hooks.json`, and `.cursor/hooks.json`. The proposed denied command is
never executed. It creates a disposable untracked file so the denied
`git clean -fd` probe threatens real state the guard must preserve. It asserts
a stored session with the correct executor and canonical workspace path,
the harness's denial wire format, and affirmative allow/deny evaluation receipts
from nonempty chains without timeouts. A zero CLI exit alone cannot pass.
Claude denial uses exit 2 with the blocking reason on stderr; Codex and Cursor
return their structured denial decisions on stdout.
Missing diagnostic telemetry means insufficient proof, not proof of a product
fault. It then runs `yoke dev setup --editable-install` and a small
`yoke watch pytest --local` subset through `uv run --frozen` in the source
environment. The product test cluster resolves already-installed embedded
Postgres binaries, falling back to system PATH when none are installed. The
pytest wrapper preserves executable access when it isolates machine config. The
smoke uses a short disposable socket root, retains failed watcher/server
captures, and stops that test cluster. Cleanup uninstalls macOS's disposable local
relay before stopping the local cluster and removing its scratch directory.

Run through `qa.plan_execution.begin` using the standalone adapter:

```text
yoke watch qa-plan -- --plan product-smoke --project yoke --checkout-path /absolute/clean/checkout --expected-branch PUBLISHED_REF --expected-sha FULL_SHA
```

Read `yoke qa plan run --help` before choosing source bindings or continuation.
The published ref must already name that exact commit. The runner records one
standalone execution, frozen case, CI run URL, actual head SHA, and conclusion;
all three jobs must pass for the case to pass. It publishes no lane and changes no
item or deployment gate. GitHub registers a new dispatch workflow from the
default branch, so its first real run follows its merge there.

Every failure names its step and capture file, including malformed JSON,
command startup errors, and hook assertions. Onboarding's initialization
diagnostics go to stderr so its `--json` stdout remains one JSON document.
Local relay discovery preserves a virtualenv interpreter's directory when
finding its installed `yoke` console script, even when Python is a symlink.
Fresh local setup records the actor returned by universe birth after writing
the local connection, so every installed harness can register against it.

Read `yoke qa plan get product-smoke --project yoke --full` for the saved case
and evidence. Each job uploads `product-smoke-evidence`: `report.json`, session
and evaluation reads, exact command captures, and failure diagnostics.
No hosted Yoke token, harness account, provider secret, or preinstalled relay
supervisor is needed by the smoke jobs. macOS onboarding installs its own
local relay. Harness login happens only when refreshing fixtures.
Self-host bring-up and relay supervision are separate checks.

## Refresh native recordings

Yoke source repo only: the corpus in `tests/fixtures/harness-sessions/` records native hook stdin,
its harness version, and the harmless one-line prompt. Refresh it when a
harness minimum version changes or a native payload shape changes.
Use an operator-authorized test account on a registered test host and hold
its `QA_HOST:<machine>` coordination claim. Wait when another session owns it.

```text
yoke dev run -- python3 runtime/api/tools/native_hook_capture.py --machine TEST_MACHINE --harness claude --output tests/fixtures/harness-sessions/claude.json # Yoke source repo only
```

Repeat for `codex` and `cursor`, then release the host claim. The helper copies
locally authored recorder code to an isolated remote scratch Git project and
opens exactly one native session. Its recorder allows a harmless shell call
and denies the second call; it does not execute the denied command. Codex trusts
only the two known recorder handlers for that invocation using the existing
hook hash implementation. No sandbox/permission bypass flags are used.

On macOS, add `--gui-session` when the SSH security session cannot access the
test account's unlocked login keychain. This runs the same recorder through
Terminal.app in the normal GUI login session. It does not unlock a keychain,
copy credentials, or change authentication settings.

Review the redacted recordings before committing: session/conversation/tool ids,
machine/account ids, paths, and account-bound data must not remain. The replay
substitutes fresh session identities, disposable workspace/transcript paths,
and probe commands while preserving native wire structure and other fields.
Absent transcript paths stay absent; present transcript filenames match the fresh session.
If a harness is signed out or its keychain is locked, ask the test-account
operator to restore access; capture must not enter or extract credentials.
