# Steer — choose level, then let the launch plane place it

New launches only: running session retains its attested selection. Judge live
remaining leg, not title/starting model: SENIOR default for definition/
implementation/review; JUNIOR mechanical/small bug/docs/cleanup; INTERN trivial
specified; PRINCIPAL very complex debugging/design. Read fleet levels dry-run
for option/machine/scoped pools/headroom/reset/blocker and live workers before
choosing. No capacity means actual refusal, not a guessed spare surface.

## Item-bound --level sets every-stage override

```text
yoke workflows item get PREFIX-N --json
yoke session-control launch create --project P --item PREFIX-N --level JUNIOR --level-reason "well-specified text change" --idempotency-key K
```

Create atomically records level min=max with reason (default launch-time level),
then launches; failure writes nothing. Receipt item_level/Item level confirms
override, preventing level_change at next stage. Omitted --level reads effective
stage and writes no override. Preview/itemless/exact --surface selection places
one launch only, no temporary item claim. Pinned item_posture_allowlist must
permit level; published current version does not repin existing item.
item_level_not_recordable requires control-plane operator compatible version
and workflows item migrate preview before checked apply under covering seat.
Record prerequisite/continue other work; no blanket repin or alternate launch.

For a running item or shift/min/max, amend per help then restaff through rule 9:

```text
yoke workflows item-posture amend PREFIX-N --key level --value '{"max":"SENIOR","reason":"SENIOR is sufficient"}' --reason "steering staffing default"
yoke projects level-summary get --project {_project}
yoke universe levels get
yoke session-control launch preview --project {_project} --level SENIOR --json
```

Override shifts/clamps automatic stage default once; exact model request bypasses
it. Never restate central level options here. Preview launches nothing; weighs
all authorized machine/options against only their billed pools, spreads to idle
surfaces above 100% headroom then greatest headroom. Read level_placement with
option/machine/pool and reason, not manual imitation. Depth:
[level routing](../../../../.yoke/docs/reference/session-level-routing.md#launching-by-level).
Cursor fallback on Other Models only when Cursor Models is confirmed zero:
unreadable, low headroom or ample other pool is not exhaustion.
level_no_capacity names options/blocking pool; deliberate permissible other
level, reset wait or operator wall. Never borrow other level silently.

## Exact operator model request

--surface plus explicit model/effort/context is selection override, exclusive
with level (level_selection_conflict). Read accepted knobs and observed models:

```text
yoke session-control launch create --project {_project} --surface {_surface} --list-models
```

Manifest session_control.launch_model_selection owns accepted surface knobs;
specific model may accept fewer efforts. Native Cursor selector already naming
effort encodes once; matching separate effort accepted, conflicting refused.
Omit context unless exact variant's native label names it. Unknown availability
refreshes target machine's native probe, then preview:

```text
yoke relay probe-models --surface cursor-cli
```

Native publication observes new models immediately; missing research never
gates launch. Catalog research (models get/lookup) is facts, not level mutation.
Only operator-approved level-proposal followed by universe levels set changes
options. No catalog-driven silent preference shift.

## Restaff ladder

1. First implementation/verification failure: same worker diagnoses/corrects
   once and reruns failed check.
2. Second failure OR spec/design misunderstanding at any attempt: one level up,
   no extra misunderstanding retry.
3. Only mechanical merge/closeout/docs/cleanup remain: next leg one level down.
4. PRINCIPAL failure or next level no capacity: evidence to operator decision;
   never silent promotion/demotion.

Parked landing/delivery is not failure. Successor --level replaces earlier
override even past previous max; explain with level-reason. To change it, restaff it through
rule 9 in [worker-lifecycle.md](worker-lifecycle.md): checkpoint live stage/
committed+dirty/failure/next step, terminate predecessor, verify released,
preview/create same item/current leg/new level, confirm registration/ownership.
Native resume keeps selection (Claude native restore, Codex/Cursor explicit
resend); changing level requires successor, never edit live worker.
