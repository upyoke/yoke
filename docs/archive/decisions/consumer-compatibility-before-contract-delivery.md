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

## Where it runs

One place: the release bridge, before it allocates the annotated tag. The
tag is the first irreversible act — a release refused after it leaves a tag
naming a build that never deployed — and everything downstream of it
publishes. The gate is unconditional there, because a release publishes
whatever trunk carries and there is no candidate diff to consult.

The consumer's own promotion-time check remains the final backstop behind
it. That check is what caught the mismatch originally; what it could not do
was catch it *before* publication, which is the whole gap this closes.

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

It does not gate a landing. A change that breaks the shared contract can
still merge; what it cannot do is get published without the host having been
built against it. That is the smallest shape that closes the observed
failure, and it keeps the ordering simple: a producer change and its
consumer companion can land in either order, and the release is where the
pair has to be real.

No new queue, receipt table, compatibility framework, negotiation layer,
second validator, required check, or repository-ruleset change. No private
dependency inside the engine other projects install: the gate is
repository-local tooling under `runtime/api/tools/`, invoked by the release
bridge that already holds the scoped credential, so the public fork-safe
factory workflows keep their read-only token and stay buildable by any fork.
