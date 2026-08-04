# Workflow definitions are universe data; the code owns a recognizable canon

A workflow definition belongs to the universe that holds it. What the code owns
is the canon: every generation Yoke has published, stored literally, so a
universe's rows can be *recognized* rather than corrected.

## What this replaced, and why

Boot convergence compared every stored row against a code-owned fixture **by
version number**, rewrote the row when it could, and raised when it could not.
Boot is fail-hard and runs for every tenant, so one mismatched row crash-looped
the fleet. That happened twice.

The comparison could not tell two very different things apart: a universe that
published on its own schedule, and a corrupted row. Stage exists precisely to
receive definitions before prod, so stage's numbering ran a version ahead for a
week — and every boot treated that as damage.

History was also *derived*, not stored: versions 2 and 3 were reconstructed from
the current definition by subtracting a hand-maintained list of fields. Adding a
field to a current definition therefore rewrote a historical digest, and the
failure surfaced at fleet boot rather than in CI.

## Measured before deciding

Classifying every stored built-in row against every definition the code could
produce, across both authoritative universes:

| universe | recognized at its own number | recognized at another number | unrecognized |
|---|---|---|---|
| prod  | 12 | 4 | 2 |
| stage | 8  | 8 | 6 |

Nobody had customized anything. Every "another number" row was byte-identical to
a real published generation. The unrecognized rows were generations the code had
*lost the ability to express* — the reconstruction defect, as a number.

## The model

- **Canon is code, literal and frozen**, as JSON beside the loader. It is data;
  reconstructing it in code is the defect this replaced.
- **Instances are universe data.** Version numbers are that universe's sequence
  positions, not a global identity.
- **Identity is the digest.** A row is recognized by content at whatever number
  it sits under. Recognition replaces conformance.
- **Convergence stops policing.** It makes the current definition available,
  appending at the universe's own `MAX(version) + 1`, and never rewrites,
  renumbers, deletes, or refuses to boot over what is stored.
- **Drift is reported, not punished** — a health finding scoped to the one
  universe, never a startup abort that takes the fleet with it.

The precedent is Yoke's own Pack contract: installed files belong to the
project, the baseline is recorded so an owner can preview and apply one update,
and drift is not policed.

## Publishing rule

**Canon is append-only.** A definition change appends generation N+1 and can
never alter generation N or earlier. History is data, not a function of current.

Appending updates two pins in `runtime/api/domain/test_builtin_workflow_canon.py`
— the generation counts and the fingerprint over every
`(workflow, version, digest)` triple. Nothing else should ever move them; a
moved pin with no appended generation means a published definition was edited.

## The rewrite-under-digest hazard

A migration that rewrites rows under a digest or immutability guarantee must use
the **same canonical serializer its readers use**, or it manufactures drift that
is indistinguishable from corruption. The first outage was exactly this: a
governed migration rewrote `workflow_versions` rows with a different JSON
serialization, and the digests then failed to match code that was otherwise
correct.

## Two things literal canon exposed immediately

Both were hidden by reconstruction, because a reconstructed fixture always
inherited the *current* vocabulary:

1. **Historical generations do not satisfy the current validator.** Real
   published rows carry `executor_bindings`, which today's schema rejects. The
   validator describes what is authorable now; history is older than it by
   construction. Canon is asserted structurally readable, not currently-valid.
2. **The old version-one fixtures had themselves drifted** from the published
   rows. The deleted compatibility allowlist carried an *alternate* v1 digest
   for all four workflows to paper over exactly that.

## Consequence worth stating plainly

Convergence no longer back-fills history into a universe. A newly created
universe comes up with the current definition as version 1, not a synthetic
1..N. A universe's history is what it actually published, and back-filling is
what forced version numbers to be globally meaningful in the first place.
