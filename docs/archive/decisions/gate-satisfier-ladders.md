# Gate satisfier ladders

## The problem

A gate is supposed to answer one question: was the obligation met? Yoke's
gates instead encoded one *shape* of proof, and every project that could
not produce that exact shape got the same non-answer — a silent pass.

Four worked instances, all observed in the engine:

- **The path-claim boundary** compared committed paths against declared
  coverage by diffing against the integration target. If no worktree was
  recorded, or the target ref did not resolve, it returned clear. On the
  item, "the boundary was clean" and "the boundary was never examined"
  looked identical.
- **The done ceremony** printed `No active worktree lane and no branch
  found — continuing without a merge.` to a transcript nobody keeps, and
  moved the item to `done`. Afterwards nothing recorded whether the work
  had merged, and if so against what proof.
- **The deployment guard** returned clear for an empty or `*-internal`
  `deployment_flow`, so a workflow whose delivery policy names a release
  could reach done having delivered nothing and recorded nothing.
- **Trunk resolution** fell back to the literal string `"main"` whenever
  `projects.default_branch` was blank. That guess never refuses at the
  moment the wrong branch is chosen; it surfaces much later as an
  unresolvable ref or a diff against a tree the item never branched from.

The common defect is not leniency. It is that each gate conflated *what
must be proven* with *how a full-stack project proves it*, leaving no
vocabulary for a weaker but honest proof — so the only available
behaviors were "enforce the full-stack shape" or "pass".

## The shape

A gate names an **obligation**. The obligation carries an ordered
**satisfier ladder**: rungs, highest first, each declaring the facts it
needs. At transition time the ladder resolves against the project's
extended capability registry and the highest reachable rung runs. The
item then records which rung answered.

Three rules keep it honest, and every consumer inherits them from the
mechanism rather than re-implementing them:

1. **No reachable rung is a refusal, never a pass.** The refusal names
   every rung it considered and the exact fact each one lacked.
2. **Every refusal names its remedy** — including undeclaring the
   capability that put an unreachable rung on the ladder, where that is
   the honest downgrade. Undeclaring is an operator decision; the
   runtime never makes it silently.
3. **Unknown is not false.** A fact the registry has never observed
   blocks its rung and says so, rather than reading as absent. This is
   what stops a project whose facts have not converged from being
   treated as a project that has nothing.

## Where facts come from

The registry is keyed by provenance, so a reader can always tell what
kind of claim a fact is:

| Prefix | Source | Refresh |
|---|---|---|
| `declared:` | `project_capabilities` rows and project scalars | operator-authored |
| `derived:` | `project_derived_facts` | every `project.snapshot.sync` |
| `item:` | control-plane state about one item | read at resolution |
| `observed:` | probed by the calling machine this call | one call |

Derived facts converge at snapshot sync for the same reason path context
does: they follow the project's live state, so they should be recomputed
exactly when that state is being re-read. Each row records what it was
observed from, which is how a reader tells "no remote" from "nobody has
looked".

The stored rows are a warm cache, not a precondition. A project that has
not synced since these facts existed has no rows at all, and reading
that as unknown would refuse correct work for a reason the operator did
nothing to cause — the first item to reach done after the release would
be the one that discovered it. Each observer is a cheap control-plane
read, so a missing fact is answered on the spot and marked as observed
live. The `unknown` verdict is reserved for what genuinely cannot be
answered: an unreadable catalog, or a fact no observer owns.

The split between `item:` and `observed:` is a transport fact, not a
taxonomy preference. An https control plane hands the driving machine no
database to open, so anything the control plane can see is read on the
server through `gate_satisfier.rung.resolve`, and only genuinely
machine-local observations — does this ref resolve in this worktree, did
this merge run — travel from the caller.

## Why the rung is stamped

Without a durable record, every degrade is either a silent lie or an
unrecorded skip. Two items that reached done through completely
different proofs — one merged with a green CI run, one merged on a
laptop with no remote — were indistinguishable the moment the session
ended.

`item_gate_satisfactions` holds one row per `(item_id, obligation)` with
the rung id, the transition it answered, and the fact snapshot it
resolved against. It is readable from item detail and paired with
`GateSatisfierRungStamped` / `GateSatisfierRefused` events.

The stamp is deliberately *not* load-bearing for the verdict: a gate
proceeds or refuses on the resolution, and a storage failure surfaces as
a warning. Making the recording a precondition would create a second,
quieter way to fail.

## What this does not do

The mechanism does not decide policy. Which gates a workflow lists, and
which rungs an obligation offers, stay data — a definition, a catalog
entry. Adding a rung is an authoring act with its own review; the ladder
only guarantees that whichever rung runs is named and recorded, and that
running none of them is a refusal.
