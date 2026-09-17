# /yoke steer steps 1–3 — parse, read the document, take the seat

## Scope invariants — these govern what this seat covers

- **Reading a document and covering a scope are two decisions.** `--doc
  SLUG` covers every item linked to that owning-project-plus-slug document,
  including other projects. `--plan-doc SLUG` locks the standing plan while
  the project-wide seat covers unlinked and CURRENT-PLAN members. `--project`
  alone covers that same project set and locks nothing. Two people steer
  two documents in one project at once, neither owning the whole project.
- **No two live steering claims with overlapping scopes.** Acquire refuses on
  overlap and names the holder by actor, machine, and session. A project
  seat overlaps CURRENT-PLAN document steering of that project; any other
  document seat can run beside it.
- **The link is the membership.** An item belongs to this seat's scope when
  it is linked to this document — `yoke strategy execution link ITEM --slug
  {SLUG} [--document-project P]`, or `--strategy-doc {SLUG}` at filing. Work
  this seat files names the document at intake; work it adopts from the
  frontier gets linked before it is staffed. Other links are that document's,
  or unattended when no document seat is live.
- **Workers address this seat as a role, never by its session id.** Every
  worker's mandate says `yoke say --steering`; the server resolves
  that at delivery to whichever seat covers the sending item — the one the
  worker holds, or last held, so a DONE resolves after close-out too, once.
  Nothing routes to an ended session, so releasing this seat strands no
  report: unattended mail parks and the next seat inherits it. Ending a turn
  sends no Fleet message, regardless of who launched the worker.
- **Strategy doc is both input and output.** There is no doc-less steer mode.
  An omitted slug resolves to `CURRENT-PLAN`, the near-term plan every project
  seeds; an explicitly supplied slug always wins. Read the resolved document
  before acting — its standing decisions, holds, scope bounds, and deployment
  gates included — as the standing-plan source of record for intent, priority,
  next steps, and constraints; write plan-level progress back into the same
  claimed document.
- **Several projects mean several seats.** Each explicitly named project
  resolves its own document and takes its own paired steering-scope claim
  through the same surfaces. There is no multi-project seat.

## 1. Parse and stamp

Extract the optional `{STRATEGY-DOC-SLUG}` and every `--project P`. An
operator-supplied slug wins; with none supplied, `{SLUG}` is `CURRENT-PLAN`
for every resolved project. An omitted slug is not a question to ask — it
selects the default. Resolve the project from the checkout map when no
`--project` is given, and when several are named, run steps 2 and 3 once per
project so each gets its own resolved document and its own seat:

```text
yoke projects checkout-context --field slug
yoke sessions touch --mode steer
```

## 2. Read the resolved strategy document

Read `{SLUG}` before any steering action — before the frontier, before
acknowledging reports, before staffing anything:

```text
yoke strategy doc list --project {_project}
yoke strategy doc get {SLUG} --project {_project}
```

The steering read is `strategy.doc.get` of the claimed slug, never `yoke strategy render` of the corpus.

- Document exists → extract its cold-start refresh, open-work index
  (`In flight`, `Ready to staff`, `Blocked`, `Awaiting operator decision`),
  and every standing decision, hold, scope bound, and deployment gate that
  constrains action. Treat those as the initial next-steps plan and honor
  them for the rest of the loop. Refresh or replace the live snapshot; do
  not copy historical status sections back into the active document.
- `strategy.doc.get` reports the resolved slug absent → **offer to create**.
  There is no silent create and no doc-less continuation. Only a genuinely
  missing document reaches this gate; an omitted slug never does, because it
  already resolved to `CURRENT-PLAN`.

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

Which flag carries `{SLUG}` follows how the operator asked, and the two
are never both passed:

```text
# The operator named projects, so {SLUG} resolved to CURRENT-PLAN:
yoke claims steering acquire --project {_project} --plan-doc {SLUG} --reason "steer {SLUG}"

# The operator named a document, so the seat is that document's:
yoke claims steering acquire --project {_project} --doc {SLUG} --reason "steer {SLUG}"
```

Run this once per resolved project. Either form acquires the seat and the
{SLUG} document lock in the same transaction; they differ only in coverage.
`--plan-doc` leaves the scope `{"project_id": N}`, so the seat covers
unlinked items and CURRENT-PLAN members in the project while locking {SLUG}.
`--doc` narrows to `{"project_id": N, "document": "{SLUG}"}` — `{N}` is the
document's owning project — and covers every item linked to that exact
document, including other projects. An overlapping seat (CURRENT-PLAN versus
the project seat) or a document holder refuses and leaves neither half behind.
A non-CURRENT-PLAN document seat can run beside the project seat. Do not
proceed without both halves. Keep the returned `claim_id` for wrapup release.

Acquire also hands over every role-addressed message this scope covers that
no live seat was acting on and no previous seat acknowledged. A project-wide
seat therefore inherits reports from items linked to no document at all and
from items already closed out, which a document-narrowed seat does not — the ones that
parked with no seat at all, and unacknowledged ones left by an ended seat.
Acknowledgement settles a report: successors never inherit it or count it as
awaiting a seat. The remaining mail arrives as one handoff digest, grouped by
the sending item, newest first. Read it before the first loop pass, then answer
what still needs answering with `yoke say --item PREFIX-N --stdin`.

Next: read [`loop.md`](loop.md) and run the standing loop.
