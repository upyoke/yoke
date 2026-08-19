# `/yoke do` Loop Routing — `wait` handler

Extracted from [`loop-routing.md`](loop-routing.md) so that file stays under
the 350-line cap. The pointer in `loop-routing.md` Step B's per-action
handler list points back here.

## `wait`

Print the wait header:
```
WAIT: {reason}
```

If `context.offer_diagnostics.top_eliminator.eliminated > 0`, print `Top eliminator: {filter} ({eliminated} of {candidate_total})` from `context.offer_diagnostics`. A WAIT ships the full `elimination_chain`; read the matching entry there for the `config_key` and `config_source` behind the exclusion.

**Runnable-elsewhere branch.** If `context.wait_reason == "runnable_elsewhere"`, the workspace-home project has no assignable work but other projects do. Render the recipe instead of the generic idle text:

```
{context.runnable_elsewhere_note}
Projects:
 - {group.project} ({group.count}): {group.item_refs} — invoke /yoke do from {group.checkout_path or 'the <project> checkout'}
```

Do not charge or resume an item from another checkout. This action is NOT chainable. Stop the loop.

**Lane-filtered branch.** If `context.wait_reason == "no_lane_compatible_work"`, the frontier has work but none of it is compatible with this lane. Render the lane situation instead of the generic idle text — the truly-empty wording below is reserved for the truly-empty branch.

```
This lane ({context.actual_lane}) has no compatible work right now.
{context.lane_filtered_note}
Filtered items ({context.lane_filtered_count}):
 - {item.item_id} ({item.status}): needs /yoke {item.required_path} — claim_state={item.claim_state}
 - ...
Paths blocked for this lane:
 - /yoke {entry.required_path} ({entry.count})
 - ...
Options:
 (a) Switch to a harness whose configured lane covers these paths.
 (b) Run the required step manually in this session (e.g. /yoke refine PREFIX-N).
 (c) Run /yoke feed to materialize additional lane-compatible work, if any exists.
```

**Disabled-process suppressed branch.** If `context.wait_reason == "process_suppressed_no_alternative"`, the decision engine recommended a process-backed action (`feed` or `strategize`) but `do_process_offer_<process>=false` disables it (through the project `session-routing` capability, or machine config only when no project policy resolved — `context.config_source` names which) AND no runnable items exist on the frontier. The recommendation surfaces as informational context — render the suppressed process plus the direct command and config knob so the operator can act:

```
{suppressed.process_key} recommended but disabled by {suppressed.config_key}=false; no alternative work on the frontier.
Run {suppressed.direct_command} directly to materialize work, or flip {suppressed.config_key}=true in machine config.
```

`{suppressed}` is `context.suppressed_process_recommendation`. The `original_reason` and `original_context` fields are available for debugging output if the operator wants the full engine trace.

**Truly-empty branch.** Otherwise, print the generic idle text:
```
No actionable work exists on the frontier. Check back later.
```

This action is NOT chainable. Stop the loop.
