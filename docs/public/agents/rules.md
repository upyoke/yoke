# Agent rules

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Agents](index.md) > Agent rules
<!-- /yoke:breadcrumbs -->

These rules cover judgment that no command can check for you. Commands and
hooks refuse the rest, and each refusal names its reason and its fix. Each
command's `--help` ends with its recipe. Claude-only steps live in
[Claude Code](claude.md).

## Scope

- One item belongs to one project: the project where its code lands. Ask when
  that is unclear. Code changes in another project need a linked companion
  item there. One session may run both lanes; each lane lives in its own
  item's project checkout.
- Finish the whole item, including files you find it needs on the way. A path
  claim, an overlap or a File Budget never makes a required file optional.
- When you report a blocker, name who owns it and how it clears.
- Rewriting your own lane's history is fine; the reflog is the backup. Never
  make side or backup branches.
- [Consumer proof](../verification/consumer-proof.md) checks consumer
  compatibility at release time for the exact release pair. A green run in the
  producing project proves only that project. Item merges need no consumer build.

## Failures

- A verification failure in this item belongs to this item. A future item or a
  planned path claim is not a waiver. Fix it here unless a live conflict or an
  explicit operator waiver applies.
- Update a test your change made stale. Never weaken a behavior assertion to
  make it pass.
- A flaky test is a defect. If this item caused it, or it lives in a file this
  item touches, fix it here. Otherwise file it and wait on the fix:

```text
yoke feedback --to universe --category failed --evidence 'Flaky test: TEST, CI run URL, observed outcomes'
yoke feedback promote 12345 --title 'Fix flaky TEST'
yoke items dependency add THIS-ITEM FIX-ITEM dash --gate-point integration \
  --satisfaction fact:merged --rationale 'needs the flaky-test fix merged'
yoke sessions touch --mode parked --reason "awaiting FIX-ITEM merge"
```

  If the fix is small and your work claim allows its files, fix it here instead.
- A cancelled or never-started CI job is not a verdict. Recover it with
  [failed CI job recovery](../github/index.md#failed-ci-job-recovery).
- Record the failure, the claim action and the rerun evidence. Never report
  green by pointing at future work.

## QA results

- Judge a result against the item's user outcome first. If the product meets
  the outcome but a case step cannot pass, the case is wrong: repair it through
  its registered write and rerun. If a case passes while the outcome fails, the
  product is wrong.
- After failed QA: a product defect returns the item to implementation; a setup
  failure is recorded as a blocker; an unclear cause is investigated now.
- N/A is not a pass.

## Design

- Each repeated value has one owner: `~/.yoke/config.json`, a DB capability
  setting, or one Python constant. When a contract changes, converge the stored
  documents that follow it.
- Yoke runs local, self-hosted and hosted, across environments, databases and
  tenants. Read project settings; never branch on one installation or project
  slug. Keep internal concerns out of anything external projects consume.
- Put harness behavior behind the harness-neutral owner. Before you state what a
  harness can do, read its installed manifest,
  `.yoke/harness/<harness-dir>/manifest.json` (`claude-code` uses `claude`;
  see [harness discovery](harness-discovery.md)).
- Retire an old path, its callers and its names in the same change. History
  stays in commits; a lasting reason belongs in `docs/archive/decisions/`.
- Keep required facts with their durable owner. Code must not depend on events
  being present, kept or delivered; missing telemetry proves nothing.
- Every refusal, timeout or crash names its reason and its recovery where the
  affected person or agent will look. Silent failure is not success, and a raw
  traceback is not a diagnosed refusal. A command that waits silently by design
  announces the wait first through `announce_designed_wait`.
- Test a change to a shell-command classifier against full recorded calls, not
  hand-picked samples.
- Update the surface that owns a changed behavior, and teach it elsewhere only
  where that helps the reader there. Follow the
  [teaching standard](../documentation/index.md).

## Names

Name paths, symbols, tests and prose for what they do now. Leave out item refs
(`PREFIX-1234`); plan, milestone, phase, stage, tier, slice, track, wave or
batch labels; feedback provenance; and criterion, requirement or spec ids
(`AC-<n>`, `FR-<n>`). Runtime data is the exception; in tests, build item refs from
variables or pattern matchers. Directory names explain purpose.

## Data

- The database is the authority. `.yoke/BOARD.md` and `.yoke/strategy/` are
  generated views; change them through their commands.
- Never edit an applied migration entry. Retire a wrong invariant in a new
  entry. Drops, backfills, rewrites and bulk changes on an authoritative
  database go only through the ordered migration history, never through ad hoc
  write SQL.
- A row-changing migration entry must be safe to run again: when its output
  already exists, fold into it instead of creating it again.
- Never relax a migration's compatibility class silently.
- Procedure: [databases](../databases/index.md).

## Coordination

- Read only what your work claim covers, and write only there. The claim, not a
  folder or a level label, authorizes a lane.
- When path claims overlap, decide in this order:
  1. Classify it: independent work is `coordination_only`; ordered work is a
     `--gate-point activation` edge with evidence of the order; unclear work
     goes to steering.
  2. Only the dependent item is blocked.
  3. Wait for the holder to release, coordinate with it, or ask it to narrow or
     cancel its scope.
  4. Override only as the last resort, through `yoke say --steering`
     (`yoke claims path override --help`).
- A dependency gate holds only its step. Activation: do not start or staff yet.
  Integration: work, test and open the pull request now; merge after it clears.
  Closure: work and merge now; close after it clears. Park only at the held step.
- Never discard changes, stashes or files you did not create without the
  user's authority. Commit or stash with a message first.
- A command you moved to the background is still running. Wait for it to
  exit; never start it again beside itself.
- Before you report a session dead, check its current process. Newer activity
  overrides a death record.

## Sessions

- A failure the system should have handled is a system gap. Before any manual
  recovery, find its root cause and file feedback or `/yoke idea`.
- On a watcher wake, tell the user in one sentence what changed (an item, a
  pull request, a failing test), or nothing. Use Fleet mail only for blockers,
  conflicts, red gates, decisions and results.
- After compaction, reload the skill for your current phase.
- Never enter plan mode on your own.

## Items and the Progress Log

- Write items only through typed `yoke items ...` commands
  ([body writes](../items/model/body-writes.md)).
- A Progress Log entry is a current-state checkpoint: the objective, standing
  decisions and holds, active work, blockers, the next action and links to
  evidence. Do not repeat earlier results or old status snapshots.
- Checkpoint unfinished work while you hold its work claim, before a wait, a
  handoff or a release. A terminal item already records its result: skip the
  final checkpoint, and never reacquire a claim only to write one.

## Releases

- Merge before release. The release flow owns the commits and the proof.
- The seat driving a release owns its run, its shared QA plans and its run QA.
  It never runs a member item's own cases and never closes a member item.
- A member item's owner runs that item's cases for its stage and closes it with
  `yoke merge item`
  ([QA dispatch](../deployments/qa-dispatch.md)).
- Before creating a run, check the members' flows. Use their flow or reconcile
  it openly; never change an item's flow silently. Never delete a flow a run
  references.
- Declare external resources and settings as infrastructure code in the same
  change. Import or remove anything you made by hand, and say which. An
  emergency patch needs operator approval and immediate catch-up in code.
- Credentials belong to project capabilities. Never print a secret, and never
  look for control-plane database credentials to deploy.

## Related

- [Operating with agents](index.md)
- [Claude Code](claude.md)
