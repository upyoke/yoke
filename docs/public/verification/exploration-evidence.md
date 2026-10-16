# Exploratory access and evidence

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Exploratory evidence
<!-- /yoke:breadcrumbs -->

Use the declared substrates, retain evidence and submit a verdict or decision disposition for an exploratory mission.

## Substrate Access

The review dispatch supplies an exact host command template:

```text
yoke --env <connection> qa mission host-command --item PREFIX-N \
  --execution-id <execution-id> --requirement-id <requirement-id> -- ARGV...
```

This command revalidates subject ownership, the parked execution, immutable
case snapshot, and retained lease before resolving client-local Test Machine
credentials. It accepts bounded argv rather than shell text and returns
redacted output. Every path in that argv names the **Test Machine's**
filesystem, never the calling machine's, so the session-cwd write-authority
guard exempts it from local write classification — a shell redirect written
after the argv still runs locally and stays enforced.

Missions are walked one at a time, in bundle order, because they share the
plan's one Test Machine. The walker dispatch carries the scratch path and two
commands. `walk-start` runs before any other host command: it re-reaches the
baseline the docket proved, since later cases ran (never in a continuation),
restores declared OS packages and creates the `0700` scratch. `walk-end`:

```text
yoke --env <connection> qa mission walk-end --item PREFIX-N \
  --execution-id <execution-id> --requirement-id <requirement-id> --run-id <run>
```

Where the product reads a secret on stdin, pipe it and touch no disk at all.
Otherwise every file carrying a token or password is staged inside that
directory and nowhere else, never a loose `/tmp` path. `walk-end`
removes the directory with plain OS commands (no Yoke install on the host),
restores the declared starting state, and records that restore as a
`starting_state_restore` artifact on the mission's run; it exits non-zero
naming `mission_scratch_not_removed`, `starting_state_restore_failed` (with the
`yoke test-machine reset` recovery) or `starting_state_restore_unrecorded`.
`yoke qa plan review-submit` refuses with `mission_walk_unfinished` while any
mission's scratch is still on the host. Both delete a stale owner marker.

The lease holder owns every Yoke project it creates: it appends each slug to
the item's Progress Log as created, so a replacement can finish the cleanup,
and before returning retires each with its own control-plane CLI (`yoke
projects retire --project SLUG --reason ...`), never Yoke on the Test Machine.

On macOS, append `--gui-session` when a command needs the login keychain or
window server. Three apparently different failures share one diagnosis:

- screenshot capture cannot create an image from the display;
- switching to the audit session is not permitted;
- a keychain-backed CLI reports OAuth expired and unrefreshable while its
  credential file is unchanged and the console session works.

They mean the command ran in the wrong session. Retry through the Terminal
GUI-session bridge before diagnosing broken credentials or privacy settings.

Use the declared browser-control substrate for web interaction. Test Machines
start without Yoke. A mission naming browser identities uses the managed browser
even when it installs nothing. When no identities are named, use it only if the
walk installed Yoke. The dispatch's
lease-routed `yoke qa browser setup` materializes the packaged runtime and
`yoke qa browser step --base-url URL --step-json JSON` drives it one chosen
step at a time. Without identities or a Yoke install, use the host browser
(Safari on macOS; desktop default elsewhere) through screenshots and keystrokes.
Never install Yoke on a Test Machine to get a browser.
Agents complete steps that do not need the user; personal credentials, MFA,
passkeys and permissions return a human gate naming host, substrate and resume state.
Case `method_config.browser_identities` wins; otherwise dispatch supplies project
identities covering the target origin. The walker picks the needed account,
verifies identities and uses `--identity NAME` for its steps. See
[browser sign-in identities](browser-identities.md).
The mission execution contract above governs every host command.

## Evidence Discipline

Perception is disposable. A walker may inspect hundreds of screens, DOM states,
or command outputs while deciding what to do; those observations are not
automatically evidence.

Attach only deliberate proof that makes a finding or human gate independently
understandable. The dispatch carries the single runtime-owned artifact limit,
and the shared artifact-add surface rejects attachments beyond it. Never make a
parallel run to evade the cap, and never attach credentials or secret-bearing
content.

A mission attaches evidence as bytes, never as a path on the test host. That
host's starting state is restored when the walk ends, so an artifact row
naming one of its paths outlives its own file: the row survives and the
evidence does not. The artifact-add surface refuses a mission handle this
control plane cannot read and names the byte-carrying recipe instead — the
walker's own `--content-file` when it walks on the target, or the bytes read
back through the remote command when it drives the target from elsewhere.

The ranked written report is the primary deliverable. Each finding should name
observed and expected behavior, impact, minimal reproduction, confidence, and
supporting artifact ids when present. The report must state every important
area that could not be verified and why.

## Verdict Submission

After all walker returns are incorporated, the main agent sends one complete
stdin batch through the exact `submit_command` in the dispatch:

```json
{"verdicts":[{"requirement_id":123,"verdict":"pass|fail|undetermined","rationale":"non-empty written report"}]}
```

Include exactly one row for every bundle case. `undetermined` is earned by the
artifacts already attached to that capture and requires a rationale naming what
remains undecidable. It halts the item until a project owner or operator records
the canonical evidence decision, so choosing it deliberately spends a human
interaction. If the case never ran or produced no artifact, record the failed
or `blocked_on_precondition` execution outcome instead; that asks no person and
returns failure to the scheduler. Do not map either condition to pass.

## Decision Disposition

An `undetermined` verdict raises a `qa_needs_review` decision request against
its requirement. That request exists because the walk could not determine a
verdict, so it belongs to the walk: when the plan execution reaches any
terminal state — completed, aborted, or error — every review it raised is
withdrawn in the same transaction, carrying the execution's state and its
`release_reason` onto the decision as the recorded reason. A requirement that
another live execution is still walking is retained; the subject-state
contract refuses to withdraw a decision whose subject has not ended.

Termination preserves [review authority for completed captures](requirement-state.md). An execution whose owner has
stopped reporting progress is reaped into `aborted` with `release_reason`
`stale-heartbeat` after 30 minutes without a heartbeat — unless its owning
session is live and parked, which is a declared hold rather than an absence
(see *Holding a Walk, and Continuing a Settled One*). Reaping is
deliberately blind to row vintage: a stranded execution written before
executions carried an execution target still settles, because resolving that
target is a precondition for *running* an execution, not for abandoning one.
For the same reason abandoning a non-progressing execution is open to any
session on its subject — the session that owned a stranded execution is by
definition the one that is no longer there — while a live execution, or one
whose owner is parked and still holding it, keeps its owner-only guard.

That parked-owner exemption leaves one execution nobody can end. A member
parked on a release wait holds an item-level execution its own walk opened,
and when the run delivering that member scopes it a run-bound execution
instead, the run-bound one produces the evidence while the item-level row
stays live forever: the done gate reads any live item-level execution as
unsettled, so the member can never close. Release settlement resolves it
without touching the owner-only guard, because the only rows it takes are
ones that recorded nothing at all — cursor still at zero and no
`qa_plan_execution_results` row. Such a row carries no evidence, so aborting
it discards none; it ends with `release_reason`
`superseded-by-run-scoped-item-qa`. An execution that recorded any result
keeps blocking and keeps its owner. Terminalizing one of these blockers by
any route replays the settling run's settlement on that same event, so a
shared gate that already passed never waits on a hand re-drive.

Reaping and withdrawal run together whenever the Inbox is read, so a reader
never sees a blocking row that blocks nothing. Run the same convergence
deliberately, with a receipt naming what was reaped, withdrawn, and retained:

```text
yoke decision-requests dispose-ended [--project-id N ...] --json
```

The pass is kind-blind: it applies each kind's own subject-state contract, so
it also releases, for example, a strategy-revision review that a later
revision has superseded.

## Related

- [Exploratory missions](exploration.md)
- [Browser identities](browser-identities.md)
