# Real harness Machine QA

`real-harness-hooks` is a manual project plan using existing `terminal-check`
cases. It needs persistent Test Machines with signed-in Claude, Codex and Cursor
captured in their sealed golden baselines. No harness or product credentials
enter CI or move from the operator's machine. Windows runs the native Linux CLI cases inside its registered WSL2 home.
Follow the Machine QA Pack's [per-OS provisioning guides](../../../../packs/machine-qa/versions/1.3.7/files/docs/packs/machine-qa/host-provisioning.md) for all host preparation and saved-state proof.

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
then installs the shell launcher. Standalone Machine QA uses the existing per-case
protocol, so every harness starts from its own golden restore rather than sharing
the preceding harness's local universe. Baseline-group lookup also recognizes a
standalone execution as its unique subject and never mixes evidence from two runs.
Host restoration, desktop prerequisites and failure recovery are specified
only in the corresponding Pack procedure linked above.

Exploratory mission preparation records failures before any walker dispatch.
The QA run's `raw_result.preparation.evidence` and the plan capture retain a
bounded, credential-redacted `preparation_failure` with its phase, diagnostic,
stdout, stderr, exit code and recovery. `baseline_outcome` names `not_started`,
`started` (restore attempted but not proved), or `completed` (restore proved),
and retains the returned baseline receipt when available. A later package or
scratch failure does not erase a completed baseline. Inspect this evidence and
reconcile the host state before retrying; a planned `scratch_path` is created
only when `scratch_created` is true. Local preparation uses the caller's source
checkout; the authority serving the control plane records its QA outcome.
Package-fixture apt failures retain the operation and package arguments in the
diagnostic, apt's own exit code, and its captured stdout/stderr rather than only
the remote Python process's error. Output is redacted before it is bounded at
the credential-owning client.

For a delivery case reusing another mission owner's preparation, run
`python3 ops/qa/mission_preparation_evidence.py --project P --holder-plan PLAN --case-key CASE --stage STAGE`
through item-scoped deployment QA. It reads recorded evidence only and requires
a holder proof bound to the current deployment run, named stage and candidate,
against the same target; a pre-release reproduction cannot pass it. The QA
requirement binding proves the deployed subject without reading unprojected
run columns. Coordinate that execution with its
holder before running the evidence case. The Command runner supplies the
deployed candidate checkout; a lane-source wrapper would switch that subject
and is refused.

The case installs the candidate wheels in a separate
environment, onboards a throwaway Git project into a disposable local universe
with GitHub disabled, and invokes the signed-in native CLI. Linux uses tmux
transcripts; macOS uses the GUI terminal bridge and its login keychain context.
The driver's first prompt is `run \`yoke status\` in the shell, then stop`.
A second native session attempts `python3 -c 'import yoke_core.api.service_client'`,
which the direct-import guard denies. It invokes no API function even if the guard
breaks. Module help is not a denied probe.

The native environment binds `XDG_BIN_HOME` to the candidate executable directory.
The driver verifies the hook shell resolves that candidate before either probe;
the restored stable launcher cannot shadow the candidate through its PATH prefix.

Passing requires exactly one new session for each probe with the correct executor
and workspace, evaluated native hook records, and affirmative allow/deny
`PreToolUse` decisions. Model prose and native CLI exit status are diagnostic only.
Missing telemetry is unavailable evidence, never a passing product verdict.
Runner exceptions close the execution with a bounded diagnostic reason; the
returned case result retains the full error for repair before a fresh run.
The driver emits `REAL_HARNESS_PROVED` only after those assertions and cleanup.
Each native prompt has a 120-second budget. Once the status probe begins, the
terminal recipe waits for `REAL_HARNESS_COMPLETE`, including failed probe reports.
That marker alone cannot pass the case.
The existing Machine QA runner records its transcript and verdict in the project
QA execution; local session ids and event ids are retained in the transcript.
Failed probe reports retain the session/event evidence already collected.

The driver uninstalls its disposable relay, retires the machine it onboarded,
and stops local Postgres on both operating systems. Every cleanup runs even if
an earlier cleanup fails; any failed cleanup prevents a passing proof.
Its scratch captures remain for diagnosis until the next golden reset. A native
authentication or bridge failure is a named prerequisite failure governed by
the corresponding Pack procedure. Hosted relay supervision and launch are verified separately.
