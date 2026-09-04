# Consumer compatibility is proven before contract delivery, not after

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
*consumer* against the exact candidate before the candidate was accepted.

## The rule

A producer-only green run proves the producer and nothing else. Where one
project ships a contract another builds against, the consumer's own build
is part of delivery evidence — not a downstream discovery.

Three properties make that real rather than aspirational:

- **The proof names both revisions.** The consumer builds against the exact
  candidate commit, never a version literal, a branch name, or a short sha
  the consumer would resolve against whatever it means there. The revision
  the consumer proved comes back from its run's head commit, and a success
  that names no readable revision is unproven rather than proven.
- **Missing evidence refuses.** Absent proof, failed proof, and proof that
  cannot be attributed to this candidate are the same answer: not
  deliverable. A gate that passes because it could not look is
  indistinguishable from one that looked.
- **The consumer owns the verdict.** The producer's gate decides *when*
  proof is required and adopts the consumer's conclusion. It does not
  re-implement compatibility, compare version literals, or hold a second
  opinion.

## Where it runs

Two boundaries, because they answer different questions.

**Before a landing.** `consumer-compatibility` is a required context in the
merge-queue ruleset, produced by `.github/workflows/yoke-consumer-compatibility.yml`
on both pull requests and merge groups. Only a *required* check gates a
landing — a red advisory check does not stop a queue entry — so an advisory
would not have stopped the change that caused this. Applicability comes from
the shipped asset contract itself rather than a hand-kept path list, so the
trigger cannot silently stop matching when an asset moves.

**Before the release tag.** The release bridge re-proves the pair
unconditionally before allocating the annotated tag, because the tag is the
first irreversible act and both trunks move between a landing and a release.
The consumer's own promotion-time check remains the final backstop behind
both.

## The ordering problem, and why companion branches exist

A change that breaks the shared contract cannot be proven against the
consumer's trunk: trunk still implements the old contract, so the honest
answer is red. The consumer's companion change has the mirror problem — it
cannot be proven against the last published product either. Demanding trunk
on both sides deadlocks the pair, and waiting for publication to break the
tie puts publication *inside* the cycle it is supposed to conclude.

The resolution is symmetry at the pull-request boundary and trunk at the
release boundary. Each side names the other's companion branch and proves
against that candidate source; the product side does it with a
`Consumer-candidate: <branch>` trailer on a commit in the candidate range,
which the gate reads from the same commit range it measures its scope over.
Selection therefore rides the change that needs it and is reviewable in it.

That lets the pair merge in either order without waiving anything, because
the release boundary never accepts a companion: it proves against trunk,
unconditionally. A half-landed pair can merge; it cannot ship.

## What was deliberately not built

No new queue, receipt table, compatibility framework, negotiation layer, or
second validator. No private dependency inside the engine other projects
install: the gate is repository-local tooling, and the credential-bearing
workflow is kept out of the public fork-safe factory, which keeps its
read-only token and stays buildable by any fork. A fork touching the shared
surface gets a named refusal that says a maintainer must run the check,
rather than a green that means nothing.
