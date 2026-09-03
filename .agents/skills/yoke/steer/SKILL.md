---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a required strategy doc."
argument-hint: "<STRATEGY-DOC-SLUG> [--project P]"
---

# /yoke steer {STRATEGY-DOC-SLUG} [--project P]

Itemless steering loop. A harness session claims the steering scope of one
strategy document, holds that document, and keeps that scope moving:
read the standing plan, reconcile it with the live frontier, consume worker
reports, write plan-level state back into the doc, hand work to executors,
staff unpicked runnable items, and escalate only decisions that need a human.
The coordinator never implements. Steering covers every pinned workflow;
each item keeps its own workflow and routed entrypoint from intake through
its live merge or release boundary.

Steering means continuous small course corrections while something else
provides the power. The stored claim kind is a **steering-scope claim**;
the skill id is **steer**. Do not invent a "steer claim".

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Registered operation authority

| Function id | CLI adapter |
|---|---|
| `claims.steering.acquire` | `yoke claims steering acquire --project P [--doc SLUG] [--reason TEXT]` |
| `claims.steering.release` | `yoke claims steering release CLAIM_ID --reason TEXT` |
| `claims.steering.list` | `yoke claims steering list --project P --active-only` |
| `strategy.doc.get` | `yoke strategy doc get SLUG [--project P]` |
| `strategy.doc.create` | `yoke strategy doc create SLUG --stdin [--project P]` |
| `strategy.execution.link` | `yoke strategy execution link ITEM --slug SLUG --project P` |
| `items.create` (Dash) | `yoke dash "TITLE" "INSTRUCTION" --strategy-doc SLUG --execution-instructions-considered` |
| `items.detail.get` | `yoke items detail get PREFIX-N --json` |
| `workflows.item.get` | `yoke workflows item get PREFIX-N --json` |
| `claims.work.acquire` | `yoke claims work acquire --item PREFIX-N --reason TEXT` |
| `claims.work.release` | `yoke claims work release --item PREFIX-N --reason TEXT` |
| `steering.report.get` | `yoke steering report get [--project P]` |
| `session_control.launch.preview` | `yoke session-control launch preview --project P --surface S --json` |
| `session_control.launch.create` | `yoke session-control launch create --project P --surface S --item PREFIX-N --idempotency-key K` |
| `session_control.launch.get` | `yoke session-control launch get LAUNCH-ID --json` |
| `session_control.launch.list` | `yoke session-control launch list --project P` |
| `session_control.launch.reconcile` | `yoke session-control launch reconcile LAUNCH-ID --json` |
| `session_control.launch.retry` | `yoke session-control launch retry LAUNCH-ID --json` |
| `session_control.surface_policy.disable` | `yoke session-control surface-policy disable --project P --machine M --surface S --reason TEXT` |
| `session_control.surface_policy.enable` | `yoke session-control surface-policy enable --project P --machine M --surface S` |
| `session_control.surface_policy.list` | `yoke session-control surface-policy list [--machine M]` |
| `session_control.session.terminate` | `yoke sessions terminate SESSION-ID --reason R` |
| `session_control.message.send` | `yoke say --item PREFIX-N --stdin` (workers reply with `yoke say --steering`) |
| `session_control.message.acknowledge` | `yoke messages acknowledge MESSAGE-ID` |
| `charge.schedule` | `yoke charge schedule --project P` |
| `deployment_runs.create` | `yoke --env <cp>-db-admin deployment-runs create PROJECT FLOW ...` |

Do not invoke `/yoke feed`. Feed and steer are unrelated.

## Invariants

- **Itemless.** This session holds no work item. One atomic steering acquire
  pairs the steering-scope claim with its strategy-doc lock; together they
  are its authority. The doc and its linked items ARE the surviving state.
- **A seat covers a scope, not a project.** `--doc SLUG` takes the seat for
  that document, covering exactly the items linked to it; `--project` alone
  takes the whole project and locks no document. Two people steer two
  documents in one project at once, neither owning the whole project.
- **No two live steering claims with overlapping scopes.** Acquire refuses on
  overlap and names the holder by actor, machine, and session. The project is
  the outer key, so a project seat and any document seat inside it are the
  same territory; two different documents are not.
- **The link is the membership.** An item belongs to this seat's scope when
  it is linked to this document — `yoke strategy execution link ITEM --slug
  {SLUG}`, or `--strategy-doc {SLUG}` at filing time. Work this seat files
  names the document at intake; work it adopts from the frontier gets linked
  before it is staffed, or it stays invisible to this seat's report and its
  worker's `--steering` reports route to the project seat instead.
- **Workers address this seat as a role, never by its session id.** An
  unrelayed worker's mandate says `yoke say --steering`; the server resolves
  that at delivery to whichever seat covers the sending item — the one the
  worker holds, or last held, so a DONE resolves after close-out too, once.
  Nothing routes to an ended session, so releasing this seat strands no
  report: unattended mail parks and the next seat inherits it. A worker this
  seat launched sends no DONE at all; its turn-end text is that report.
- **Strategy doc is both input and output.** There is no doc-less steer mode.
  Read it as the standing-plan source of record for intent, priority, next
  steps, and constraints; write plan-level progress back into the same
  claimed document.
- **Vocabulary is steering.** Identifiers, refusal text, and labels use
  steering-scope claim, steering claim holder, steering scope. "Coordinator"
  is acceptable role prose. Never name a durable identifier coordination
  or coordinator. Avoid the bare phrase "steer claim".
- **No new scheduler.** The loop is message wakes plus periodic frontier
  checks through existing surfaces. Do not add or call feed.
- **Every workflow stays itself.** Read each item's pinned `workflow_id` and
  the scheduler's `next_step`; never convert or re-file incoming work to make
  it Dash-shaped. One worker owns that one item across its routed legs.
- **Dash is the filing default, not the steering boundary.** New work filed by
  the steerer uses Dash unless it is genuinely laneless, merge-free Task work
  (`yoke task TITLE INSTRUCTION --execution-instructions-considered`), needs
  Issue, Epic, or Blitz structure, or the operator directs another workflow.
  Pass `--strategy-doc {SLUG}` on either so the filed item lands inside this
  seat's scope.
- **Workers merge; the steerer batches delivery.** Worker mandates prohibit
  deployment-run creation. The loop pins one release SHA, deploys batches,
  and completes any item parked at its release boundary afterward.
- **A worker blocked on an upstream item stamps parked before going quiet.**
  `yoke sessions touch --mode parked --reason "waiting on PREFIX-N"`. That
  write persists; reporting or reading the control plane does not unpark.
  Leave parked by stamping a working mode (`yoke sessions touch --mode dash`).
- **Autonomous.** Invoking `/yoke steer` authorizes the loop. Do not wait
  for confirmation before claiming, reading the frontier, acknowledging
  reports, launching workers, or writing the doc — except the documented
  offer-to-create and operator-escalation gates.

## 1. Parse and stamp

Extract `{STRATEGY-DOC-SLUG}` and optional `--project P`. Resolve the
project from the checkout map when `--project` is omitted:

```text
yoke projects checkout-context --field slug
yoke sessions touch --mode steer
```

## 2. Require a strategy document

```text
yoke strategy doc list --project {_project}
yoke strategy doc get {SLUG} --project {_project}
```

- Named doc exists → extract its cold-start refresh, open-work index
  (`In flight`, `Ready to staff`, `Blocked`, `Awaiting operator decision`),
  and every standing decision that constrains action. Treat those as the
  initial next-steps plan.
- No slug, or `strategy.doc.get` says the slug is absent → **offer to
  create**. There is no silent create and no doc-less continuation.

Offer shape (wait for an explicit operator yes before creating):

```text
No strategy doc {SLUG} in project {_project}.
Create it with a minimal steer structure (objective, frontier, decisions,
gates) and continue? [yes/no]
```

On yes:

```text
printf '%s' "$SEED" | yoke strategy doc create {SLUG} --stdin --project {_project}
```

`$SEED` is a markdown document with exactly those four headings:
`# Objective`, `# Frontier`, `# Decisions`, `# Gates`. After create,
continue as if the doc already existed. On no, stop.

## 3. Acquire the paired steering authority

```text
yoke claims steering acquire --project {_project} --doc {SLUG} --reason "steer {SLUG}"
```

This one function call acquires the document's seat and its document lock in
the same transaction. The seat's scope is `{"project_id": N, "document":
"{SLUG}"}`, so it covers exactly the items linked to {SLUG}. An overlapping
seat or a document holder refuses the call and leaves neither half behind —
the refusal names the holding actor, machine, and session, and a seat on a
different document in the same project is always available. Do not proceed
without both halves. Keep the returned `claim_id` for wrapup release.

Acquire also hands over every role-addressed message this scope covers that
no live seat was acting on and no previous seat acknowledged — the ones that
parked with no seat at all, and unacknowledged ones left by an ended seat.
Acknowledgement settles a report: successors never inherit it or count it as
awaiting a seat. The remaining mail arrives as one handoff digest, grouped by
the sending item, newest first. Read it before the first loop pass, then answer
what still needs answering with `yoke say --item PREFIX-N --stdin`.

## 4. Run the standing loop

Read [`loop.md`](loop.md) and follow it. The loop is the rest of this
skill. Worker launch rules live in
[`worker-lifecycle.md`](worker-lifecycle.md) and ship in this first
version — do not defer them.

## 5. Wrapup releases claims

Release is mark-complete. An abandoned coordinator is reclaimed by the
stale sweep. Before ending the session, release the steering claim; its paired
document lock leaves in the same transaction:

```text
yoke claims steering release {CLAIM_ID} --reason "steer wrapup"
```

Then `/yoke wrapup` if the operator asked for a session close. Do not
release the paired document directly while the seat is live; that refusal
teaches this paired release instead.

## Seat hygiene (token economics)

- Every wake resends the seat's whole transcript, so cost-per-wake grows
  with transcript length. When the transcript is heavy and the fleet is
  quiet, prefer an orderly handoff — update the strategy doc's Live
  status, release the seats, and let a fresh session cold-start from the
  doc — over dragging a long transcript through every subsequent wake.
- When self-scheduling a wakeup, pick the delay for what is actually
  being awaited and avoid landing just past the prompt-cache window:
  wake densely while genuinely active or rarely with a batched pass —
  the just-expired middle pays full transcript price per wake for
  nothing.

## Surface disable marks

This is a manual circuit breaker, not a state machine. Do not count
failures, auto-trip, auto-clear, or probe on a timer.

When a run of same-surface worker failures carries a vendor-side
signature (quota exhausted, launch path broken on that harness), disable
that `(machine, surface)` and rebalance new launches onto the other
harnesses:

```text
yoke session-control surface-policy disable --project {_project} --machine M --surface S --reason vendor_signature
```

Before re-enabling, run one cheap canary launch on that surface. Clear
the mark only after that canary succeeds:

```text
yoke session-control surface-policy enable --project {_project} --machine M --surface S
```

Escalate to the operator instead of marking when failures are
unclassified. Unclassified failures can be Yoke-side; disabling a
healthy harness for our own bug is the failure mode to avoid. Marks
gate new launches and native-resume spawns only; in-flight sessions
stay up.
