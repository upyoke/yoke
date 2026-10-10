# Steer — resolve document and paired authority

Strategy doc is both input and output: no doc-less mode. Reading a document
and covering a scope are two decisions. Membership is its exact owning-project
plus slug link; link adopted work before staffing, and name --strategy-doc at
filing. Several projects mean several seats. There is no multi-project seat.

## Parse and read first

An operator-supplied slug wins; an explicitly supplied slug always wins.
Otherwise `{SLUG}` is `CURRENT-PLAN` for every resolved project. An omitted
slug is not a question to ask. Resolve an omitted project from its checkout;
run steps 2 and 3 once per project so each gets its own resolved document and
its own seat:

```text
yoke projects checkout-context --field slug
yoke sessions touch --mode steer
yoke strategy doc list --project {_project}
yoke strategy doc get {SLUG} --project {_project}
```

Read `{SLUG}` before any steering action — before the frontier, before
acknowledging reports, before staffing anything. Use strategy.doc.get of that
slug, never corpus render. Extract cold-start refresh, open-work index
(In flight/Ready to staff/Blocked/Awaiting operator decision), standing decisions,
holds, scope bounds, and deployment gates: every standing decision, hold,
scope bound, and deployment gate that constrains action survives in the plan.
Refresh the live snapshot; do not restore historical statuses.

Only a genuinely missing document reaches this gate; an omitted slug never
does, because it already resolved to `CURRENT-PLAN`. Offer to create objective,
frontier, decisions and gates, then wait for explicit yes. No means stop;
unavailable/failed read is not absence. On yes, supply a Markdown seed with
exact headings # Objective, # Frontier, # Decisions, # Gates:

```text
yoke strategy doc create {SLUG} --summary "Document purpose" --state draft --stdin --project {_project} < SEED_FILE
```

## Acquire one complete pair per project

```text
# Project request: lock the plan without narrowing project coverage.
yoke claims steering acquire --project {_project} --plan-doc {SLUG} --reason "steer {SLUG}"
# Explicit document request: cover its linked work, including other projects.
yoke claims steering acquire --project {_project} --doc {SLUG} --reason "steer {SLUG}"
```

Use one form, never both. `--plan-doc` leaves the scope `{"project_id": N}`,
so the seat covers unlinked items and CURRENT-PLAN members in the project
while locking the plan. --doc narrows to owning project+exact document and
all its linked items, including other projects. Project and CURRENT-PLAN
document seats overlap; other document seats can coexist. Overlap/doc holder
refusal names actor/machine/session and leaves neither half acquired. Proceed
only with both halves; retain claim_id for paired release. A project seat
alone covers its project set and locks nothing; this skill still requires
its resolved document. Releasing one of several held seats releases only
its paired lock: verify remaining inventory before further edits.

Workers address the ROLE with yoke say --steering, resolved from held/last-held
item rather than a copied session UUID. Unattended mail parks; ending a turn
sends no Fleet message. Acquire hands over unacknowledged scope mail newest
first grouped by item, including eligible closed/unlinked project reports.
Acknowledged reports are never inherited or awaiting a seat. Read the full
handoff digest before the first pass, then substantively answer unfinished
requests through yoke say --item PREFIX-N --stdin.

Continue to [loop.md](loop.md).
