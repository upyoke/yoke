# Frontier

The **Frontier** is what can run now, ranked with reasons. You steer; a
harness executes.

## Modes that move it

| Command | Role |
|---|---|
| `/yoke charge` | Pick up the next runnable item and dispatch |
| `/yoke feed` | Maintain dependency graph; optionally materialize ideas from strategy |

## Read the board

Frontier rows reflect lifecycle status, blocks, freezes, claims, and
dependencies. Blocked items stay at their lifecycle stage with a reason;
frontier routes them to wait until unblocked.

The Frontier page draws six bands, in order: **Waiting**, **On hold**,
**Ready**, **Active**, **Release** and **Done (24h)**. Waiting is a graph of
unsatisfied dependency edges at the start, merge and close gates
(`coordination_only` edges never block, so they are never drawn). Its first
column, *Holding work up*, holds every item with no unsatisfied blocker that
something waits on, whatever its band; later columns are steps behind, by the
longest unsatisfied path. The longest chain that can still move is drawn
heavier. Each tile names what holds it — "Starts after <blocker> merges", "Can
build now · lands after …", "Can't close until … is live on prod" — and its
hover lists each edge's rationale. A tile that cannot move on its own is red
with its reason: a frozen or blocked root others wait on, a cancelled
blocker, an environment no delivery flow of the blocker reaches, or a
deadlock (two items waiting on each other). Everything downstream reads
`Stuck upstream: <item>`. Selecting a tile opens every blocker with its
gate, condition, where it is now and its rationale, every dependent, and the
item's full card. On a phone the graph is an outline of each chain.

On hold holds waiting items held for a reason of their own — frozen,
blocked, an owner that stopped answering — that nothing waits on. The
project filter keeps every item in the selected projects plus every item tied
to one through any dependency chain, in any project, in every band. Every
session chip on the page opens its session card as a popover.

The graph reads `dependency_edges` from `frontier.list`. A serving build
that predates that field gets a named refusal in Waiting and On hold, with
its serving floor, rather than a graph guessed from reason text.

Release and recent Done cards show delivery by landing and environment. A
candidate run appears while it carries a landing awaiting delivery there;
the first successful run settles that landing in that environment. Later runs
that only contain the same code remain in run history. Stage delivery does not
settle Production delivery, and a new landing of the same item starts a new
delivery. The card names the item's single flow once and shows one current
row per environment. Once the item has merged, a sub-line under the flow
header reads `merged <relative time> · PR <number>`; the PR links to its
repository when known. Unmerged items have no merge sub-line. A `member`
run owns the item's delivery; a `carried`
run contains its code without owning its QA. Member outcomes use that member's
own QA: a passed item reads `deployed · QA passed` even while its run stays
open. Only that finished member gets a sub-line naming the run's remaining
wait. In-progress rows name the current stage and elapsed time; an environment
awaiting a run reads `not yet · next release`. The run id links to its history.

```bash
yoke items dependency list PREFIX-N
```

## Operator stance

- Charge when you want motion on ready work
- Feed when strategy or the dependency graph is stale
- Do not delete required files from an item to clear a path-claim conflict —
  coordinate or serialize instead

Algorithm detail: [reference/charge-frontier.md](reference/charge-frontier.md).

Ready cards show readiness and item context without a raw CLI command line.
