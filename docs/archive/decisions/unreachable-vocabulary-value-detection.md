# Detecting a surviving definition of a removed feature

## The defect class

`HC-obsoleted-terms` enforces one direction: when a surface is retired, every
reference to it must go. It fires because the reference no longer resolves —
something dangles.

The inverse shape has no guard and leaves nothing dangling. A feature is
removed while its constant, its membership in a closed vocabulary, and the
branch comparing against it all survive. Every reference still resolves. The
code is simply unreachable forever, and no compiler, linter, or test notices,
because nothing about it is malformed.

The worked instance: commit `4fdf811a7` removed the steering staffing
backstop. `LAUNCH_ORIGIN_STEERING_BACKSTOP` survived — defined, still a member
of `LAUNCH_ORIGINS`, and still compared against in
`sessions_steering_visibility._launches`. Nothing wrote that origin;
`LAUNCH_ORIGIN_OPERATOR` is the default on both launch dataclasses and no code
set the other value.

The consequence was not cosmetic. The dead comparison sat in the first arm of
an `if`/`elif` whose second arm assigns a different field only when a session
is *not* launched. With the first arm permanently unreachable, correctly
launched sessions fell into a hole — excluded from the second arm for being
launched, never reached by the first because the origin never matched — and
rendered nothing. The visible symptom was blank session cards on two of three
harnesses, and finding the cause took a full root-cause investigation back to
an incomplete removal months earlier.

## What was measured, and rejected

The obvious generalization is "a closed enum member that nothing assigns".
It was implemented and run against the tree before being rejected on evidence.

| Rule | Hits | Verdict |
|---|---|---|
| Vocabulary member with no producing use in live code | 51 | Unusable |
| ...and at least one sibling member *is* produced | 20 vocabularies | Still unusable |
| ...and the vocabulary is compiled into column DDL | 1 vocabulary | Ceremonial |
| CHECK-declared value with no producer and no stored row | **1** | Shipped |

The 51 and the 20 are dominated by one healthy pattern: a validation
vocabulary whose values arrive from **outside** Python. `INSTALLATION_PENDING`
comes from a GitHub webhook. `FLOW_STATUS_DISABLED` comes from `argv`.
`MIGRATION_STRATEGY_ADDITIVE_ONLY` comes from operator-authored item JSON.
`STAGE_ENV_NAME` comes from a database row. For every one of these, having no
Python writer is *normal*, and a static scan cannot tell them apart from a dead
value: both look like a constant nothing assigns. Inspecting how each
vocabulary collection is consumed confirmed the pattern — nearly all of them
appear as `if value not in VOCABULARY: raise`, which exists precisely to admit
outside input.

The third row narrows to vocabularies the codebase compiles into the column's
own `CHECK` constraint, which is a genuinely principled boundary — such a
module asserts that this codebase owns the complete value set. But exactly one
vocabulary in the tree has that shape, and fixing it would leave the check with
an empty population and permanent green. A check that cannot fire again is not
a guard.

## What was built

`HC-unreachable-vocabulary-value`, at WARN.

The vocabularies come from the database, not from a hand-maintained catalogue:
every `CHECK (col = ANY (ARRAY['a','b',...]))` constraint enumerates the
complete set of values one column may hold. That is 65 constraints and 251
values in this control plane — real coverage of the whole persisted vocabulary
surface, and it grows on its own as tables are added.

A value is reachable on any one of three kinds of evidence. **Each can only
clear a value; none can flag one**, which is what keeps the check biased toward
silence:

1. **A stored row** carries the value, so something produced it.
2. **A literal writer** spells the quoted literal in live source outside
   vocabulary and DDL declarations — including inside SQL strings, which is how
   most writers in this codebase spell a state transition.
3. **A named producer** uses a module-level constant bound to the value
   somewhere that is neither a comparison nor the vocabulary declaration.

Only a value with none of the three, and whose definition still survives in the
source tree, is reported. A value the source no longer mentions is
database-only residue from a constraint that outlived its code: there is no
surviving definition left to remove, so the check stays quiet.

**Pairing source evidence with stored rows is the whole trick.** It is what
separates "no writer because the value is dead" from "no writer because the
writer is the outside world" — the distinction no purely static rule could
draw. Across 251 values it produced exactly one finding, the confirmed
instance, with its declaration site and its dead comparison site both named.

Test files are deliberately not writers. A fixture that constructs the value
proves nothing about live code; the surviving test is itself part of the
residue. Migrations are excluded for the same reason — they are permanent
ordered history rather than a live path, and a migration that really did write
a value leaves rows behind, which clears it through row evidence anyway.

### Known limits

- **A value spelled only as a bare literal in a comparison is missed.** Any use
  that is not plainly a comparison counts as production, so `if x == 'foo'`
  clears `foo`. Missing one finding is the acceptable failure; crying wolf is
  not, because a noisy guard gets suppressed and then catches nothing.
- **Row evidence varies by universe.** It only ever clears, so a sparse
  universe cannot manufacture a false finding — it can only surface a candidate
  the code evidence would then have to clear on its own.
- **Vocabularies enforced in application code rather than a CHECK constraint
  are out of scope.** They have no authoritative enumeration to read.
- **This is not unreachable-branch analysis.** It finds values nothing
  produces, not conditions that cannot be true. The general problem is much
  larger and was not attempted.

## The two decisions this item asked for

**How far does the check generalize?** Not to "enum members never assigned",
and the measurement above is why. It generalizes to every value a database
CHECK constraint admits — broad coverage of a precisely bounded surface —
rather than to every constant that looks enum-shaped.

**Should the guard have caught the original incomplete removal at review time,
or is the durable answer a discipline that removal takes its constants with
it?** The guard. A discipline rule was already available and did not help:
`4fdf811a7` did consider the value, and deliberately kept it with a written
rationale — that `steering_backstop` had to stay in the CHECK "because live
rows carry it". No rows carried it. `SELECT origin, count(*) FROM
session_launches` returns exactly one row, `operator`, and the same commit
message states the backstop never staffed anything. The removal was careful,
documented, reviewed, and wrong about a fact nobody checked.

That is the argument for a check over a rule. The reviewer's failure was not
inattention; it was believing an unverified claim about stored data. A rule
asks people to remember. This check verifies the exact claim the comment made,
and it is cheap enough to run on every doctor pass.

The codebase already had the right answer for the case where a retired value
must genuinely stay admitted: `RETIRED_PROJECT_KEYS` records each retired key
beside the live ones with the reason it went. The check's remediation text
points at that pattern, so a deliberate retention is written down where the
next reader will find it rather than left as a constant that looks live.
