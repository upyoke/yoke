# Frontier

The **Frontier** is what can run now, ranked with reasons. You steer; a
harness executes.

## Modes that move it

| Command | Role |
|---|---|
| `/yoke charge` | Pick up the next runnable item and dispatch |
| `/yoke feed` | Maintain dependency graph; optionally materialize ideas from strategy |
| `/yoke do` | Session offer — engine chooses resume / charge / feed / strategize / wait / escalate |

## Read the board

Frontier rows reflect lifecycle status, blocks, freezes, claims, and
dependencies. Blocked items stay at their lifecycle stage with a reason;
frontier routes them to wait until unblocked.

Release and recent Done cards show delivery by landing and environment. A
candidate run appears while it carries a landing awaiting delivery there;
the first successful run settles that landing in that environment. Later runs
that only contain the same code remain in run history. Stage delivery does not
settle Production delivery, and a new landing of the same item starts a new
delivery. A run member is labeled separately from candidate containment.

```bash
yoke items dependency list PREFIX-N
```

## Operator stance

- Charge when you want motion on ready work
- Feed when strategy or the dependency graph is stale
- Do not delete required files from an item to clear a path-claim conflict —
  coordinate or serialize instead

Algorithm detail: [reference/charge-frontier.md](reference/charge-frontier.md).
