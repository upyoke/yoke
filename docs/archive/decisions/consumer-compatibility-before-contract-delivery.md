# The hosted consumer is built before a release is published

## What went wrong

The product changed the universe app contract it ships — the declared
version the hosted host negotiates against — from 6 to 7. The producer's
own suite was green: it had been updated alongside the change. The item's
instruction excluded redesigning the host's approval page, and that
exclusion was read as excluding the host entirely, so no companion item was
filed in the consumer project and no evidence named the consumer at all.

The change merged. The release factory built and published the artifact.
Only then, during promotion, did the host's existing product-compatibility
build refuse: *host expects 6, bundle declares 7*. Two hosted releases
stopped after the artifact was already public, and both environments stayed
on their previous builds until the host was adapted by hand.

Every individual gate did its job. What was missing was a gate that ran the
*consumer* against the exact candidate before the candidate was published.

## The rule

A producer-only green run proves the producer and nothing else. Where one
project ships a contract another builds against, the consumer's own build is
part of the release, not a downstream discovery.

Three properties make that real rather than aspirational:

- **The proof names both revisions.** The consumer builds against the exact
  candidate commit, never a version literal, a branch name, or a short sha
  the consumer would resolve against whatever it means there. The revision
  the consumer proved comes back from its run's head commit, and a success
  that names no readable revision is unproven rather than proven.
- **Missing evidence refuses.** Absent proof, failed proof, and proof that
  cannot be attributed to this candidate are the same answer: not
  publishable. A gate that passes because it could not look is
  indistinguishable from one that looked.
- **The consumer owns the verdict.** This side decides only *when* proof is
  required and adopts the consumer's conclusion. It does not re-implement
  compatibility, compare version literals, or hold a second opinion.

## What it invokes

The consumer's existing required check, not a new one. That project already
runs a release-pin check on its own pull requests, which builds its host
against the pinned product wheel. Passing a candidate commit to it redirects
what it builds against — the checked-out product source instead of the
published wheel — and leaves everything else, including its own pin
validation, exactly as it was. So there is no second compatibility workflow,
no second job, and no second definition of compatible: the gate dispatches
the check that already exists and reads its conclusion.

The candidate identity survives that redirection because the consumer passes
the commit straight to its product checkout and then reads the checked-out
head back, failing if it is not the commit that was asked for. A green run
therefore cannot have tested a different product.

## Where it runs

The mandatory boundary is the release bridge, before it allocates the
annotated tag. The tag is the first irreversible act — a release refused
after it leaves a tag naming a build that never deployed — and everything
downstream of it publishes. The gate is unconditional there, because a
release publishes whatever trunk carries and there is no candidate diff to
consult.

An author can run the same gate earlier, at the merge attempt, by attaching
it to the work item as its verification case: a QA requirement bound to the
built-in `command` method, at the `reviewing-implementation` transition.
That case executes client-side in the lane, on a machine that already holds
the control-plane connection, so it reaches the consumer without putting a
credential anywhere near the public fork-safe CI. The lifecycle gate then
refuses the transition until it passes, which is what puts the answer in
front of the person merging rather than the person releasing.

That earlier run is honestly a warning rather than a wall: it is per-item
and opt-in, because the only automatic pre-merge mechanisms available are a
required status context plus a ruleset entry — deliberately not built — and
QA project defaults, which the Dash workflow's `optional_item_attachment`
policy does not consult. Publication remains the mandatory blocker either
way, so a change that skips the earlier warning still cannot be published.

The consumer's own promotion-time check remains the final backstop behind
both. That check is what caught the mismatch originally; what it could not
do was catch it *before* publication, which is the whole gap this closes.

## Binding the release to the revision that was proven

Proving a pair before the tag is not the same as shipping that pair.
Promotion is dispatched at the consumer's trunk and materializes its
environment branches afterwards, so trunk can move in between. The proof
therefore hands promotion the revision it actually read, and promotion
refuses when the trunk revision it is about to incorporate is not that one —
checked before any pin commit exists.

What is bound is *the trunk revision this promotion incorporates*, which is
exactly what the proof read. The commit finally deployed does not exist when
the binding is checked — the pin advance, and on Stage the merge, create it —
so nothing here claims to bind that.

## What this deliberately does not do

It does not gate a landing automatically. An item that attaches the
verification case cannot transition past it while the pair is red, but an
item that attaches nothing still merges; what neither can do is get
published without the host having been built against the candidate. That is
the smallest shape that closes the observed failure, and it keeps the
ordering simple: a producer change and its consumer companion can land in
either order, and the release is where the pair has to be real.

No new queue, receipt table, compatibility framework, negotiation layer,
second validator, second consumer workflow, required status context,
repository-ruleset change, commit trailer, or companion-branch pairing
protocol. No private dependency inside the engine other projects install:
the gate is repository-local tooling under `runtime/api/tools/`, invoked by
the release bridge that already holds the scoped credential, so the public
fork-safe factory workflows keep their read-only token and stay buildable by
any fork.
