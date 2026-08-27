---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a required strategy doc."
argument-hint: "<STRATEGY-DOC-SLUG> [--project P]"
---

# /yoke steer {STRATEGY-DOC-SLUG} [--project P]

Itemless steering loop. A harness session claims one project's steering
scope, holds one required strategy document, and keeps that scope moving:
read the frontier, consume worker reports, write plan-level state into the
doc, hand work to executors, staff unpicked runnable items, and escalate
only decisions that need a human. The coordinator never implements.

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
| `claims.steering.acquire` | `yoke claims steering acquire --project P [--reason TEXT]` |
| `claims.steering.release` | `yoke claims steering release CLAIM_ID --reason TEXT` |
| `claims.steering.list` | `yoke claims steering list --project P --active-only` |
| `strategy.doc.get` | `yoke strategy doc get SLUG [--project P]` |
| `strategy.doc.create` | `yoke strategy doc create SLUG --stdin [--project P]` |
| `strategy.doc_claim.acquire` | `yoke strategy doc-claim acquire SLUG --project P` |
| `strategy.doc_claim.release` | `yoke strategy doc-claim release SLUG --project P --reason TEXT` |
| `strategy.execution.link` | `yoke strategy execution link ITEM --slug SLUG --project P` |
| `steering.backstop.evaluate` | `yoke steering backstop evaluate --project P` |
| `session_control.launch.create` | `yoke session-control launch create --project P --surface S --stdin --idempotency-key K` |
| `session_control.session.terminate` | `yoke sessions terminate SESSION-ID --reason R` |
| `session_control.message.acknowledge` | `yoke messages acknowledge MESSAGE-ID` |
| `charge.schedule` | `yoke charge schedule --project P` |

Do not invoke `/yoke feed`. Feed and steer are unrelated.

## Invariants

- **Itemless.** This session holds no work item. The steering-scope claim
  plus the strategy-doc lock are its authority. The doc and the project's
  items ARE the surviving state.
- **One live steering-scope claim per project.** Acquire refuses on overlap
  and names the holder. v0 is one coordinator per scope.
- **Strategy doc is required.** There is no doc-less steer mode.
- **Vocabulary is steering.** Identifiers, refusal text, and labels use
  steering-scope claim, steering claim holder, steering scope. "Coordinator"
  is acceptable role prose. Never name a durable identifier coordination
  or coordinator. Avoid the bare phrase "steer claim".
- **No new scheduler.** The loop is message wakes plus periodic frontier
  checks through existing surfaces. Do not add or call feed.
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

## 2. Acquire the steering-scope claim

```text
yoke claims steering acquire --project {_project} --reason "steer {SLUG}"
```

On refusal, stop and report the named holder. Do not proceed without the
seat. Keep the returned `claim_id` for wrapup release.

## 3. Require a strategy document

```text
yoke strategy doc list --project {_project}
yoke strategy doc get {SLUG} --project {_project}
```

- Named doc exists → acquire its lock and treat it as the live substrate.
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

Then acquire the itemless document lock:

```text
yoke strategy doc-claim acquire {SLUG} --project {_project} --reason "steer"
```

A live Blitz already bound to this slug refuses the lock — that is the
handoff exclusion. Do not force it.

## 4. Run the standing loop

Read [`loop.md`](loop.md) and follow it. The loop is the rest of this
skill. Worker launch rules live in
[`worker-lifecycle.md`](worker-lifecycle.md) and ship in this first
version — do not defer them.

## 5. Wrapup releases claims

Release is mark-complete. An abandoned coordinator is reclaimed by the
stale sweep. Before ending the session:

```text
yoke strategy doc-claim release {SLUG} --project {_project} --reason "steer wrapup"
yoke claims steering release {CLAIM_ID} --reason "steer wrapup"
```

Then `/yoke wrapup` if the operator asked for a session close. Do not
leave either claim held after a clean stop.
