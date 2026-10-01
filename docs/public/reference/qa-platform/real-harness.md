# Real harness Machine QA

`real-harness-hooks` is a manual project plan using existing `terminal-check`
cases. It needs persistent Test Machines with signed-in Claude, Codex and Cursor
captured in their sealed golden baselines. No harness or product credentials
enter CI or move from the operator's machine. Windows awaits a supported host.

Build the candidate's five wheels in its claimed checkout and declare the exact
CLI version for each harness and operating system in a JSON document:

```json
{
  "claude": {"Linux": "2.1.285 (Claude Code)", "Darwin": "2.1.286 (Claude Code)"},
  "codex": {"Linux": "codex-cli 0.159.2", "Darwin": "codex-cli 0.156.1"},
  "cursor": {"Linux": "2026.09.28-64d2043"}
}
```

Observe macOS versions through its GUI terminal context, since an SSH keychain
refusal does not diagnose sign-in. Add its exact Cursor version after that probe.
A missing declared version refuses; it never silently substitutes another build.

```text
yoke dev run -- uv build --all-packages --wheel --out-dir /tmp/harness-wheels
yoke dev run -- python3 ops/qa/real_harness_plan.py --wheel-dir /tmp/harness-wheels --wheel-archive /tmp/harness-wheels.tar --versions-file /tmp/harness-versions.json --output /tmp/harness-cases.json
yoke qa plan create real-harness-hooks --project P --environment ENV
yoke qa plan-cases replace --project P --plan-id PLAN_ID --cases-file /tmp/harness-cases.json
yoke watch qa-plan -- --plan real-harness-hooks --project P --machine linux-lab
yoke watch qa-plan -- --plan real-harness-hooks --project P --machine test-mac
```

Read each command's `--help` before selecting source or continuation options.
The plan snapshot carries absolute staged artifact paths: regenerate its cases
from the exact candidate before each fresh execution, and preserve those files
through any continuation. The source checkout, candidate wheels and recorded QA
execution must be named together in the work item's evidence.

Each case restores `shell-preconfigured`, which first restores the golden and
then installs the shell launcher. It installs the candidate wheels in a separate
environment, onboards a throwaway Git project into a disposable local universe
with GitHub disabled, and invokes the signed-in native CLI. Linux uses tmux
transcripts; macOS uses the GUI terminal bridge and its login keychain context.
The driver's first prompt is `run \`yoke status\` in the shell, then stop`.
A second native session attempts a read-only module help request that Yoke's
registered-command guard denies. It makes no direct runtime API call and cannot
mutate state even if the guard breaks.

Passing requires exactly one new session for each probe with the correct executor
and workspace, evaluated native hook records, and affirmative allow/deny
`PreToolUse` decisions. Model prose and native CLI exit status are diagnostic only.
Missing telemetry is unavailable evidence, never a passing product verdict.
The driver emits `REAL_HARNESS_PROVED` only after those assertions and cleanup.
The existing Machine QA runner records its transcript and verdict in the project
QA execution; local session ids and event ids are retained in the transcript.

The driver stops its local Postgres and removes macOS's disposable local relay.
Its scratch captures remain for diagnosis until the next golden reset. A native
authentication or bridge failure is a named prerequisite failure: inspect the
capture, restore the GUI context or have the operator sign in, refresh the golden,
then rerun. Hosted relay supervision and launch are verified separately.
