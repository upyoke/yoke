# QA plan execution states

A plan execution records the work in progress, independently of its QA verdict.
The CLI, steering report and Workbench read the same stored `state`.

| State | Work represented | Audit result |
| --- | --- | --- |
| `active` | Ordered deterministic capture, including mission host preparation | Accurate; retained |
| `waiting` | Host queue or a recorded safe pause awaiting re-entry | Accurate; retained |
| `walking` | Capture finished and at least one mission has not handed back | Added to distinguish preparation from the informed walk |
| `awaiting_walk_review` | All mission walks handed back, or ordinary captures await independent review | Replaces the old combined walk/review state |
| `completed` | The attempt ended, including a host-contention handoff to a queued successor | Accurate; retained; completion alone never implies a passing verdict |
| `aborted` | The attempt was cancelled; completed captures can still owe review | Accurate; retained |
| `error` | The attempt stopped on an execution error; completed captures can still owe review | Accurate; retained |

Mission preparation creates the review bundle used to dispatch the informed
walker, but the execution enters `walking`. Each successful `yoke qa mission
walk-end` records a `starting_state_restore` artifact on that mission's capture
run. The final mission's receipt changes the execution to `awaiting_walk_review`
in the same transaction. An unrecorded hand-back stays `walking`: resolve the named
walk-end error and retry its exact command. Earlier missions handing back do
not finish later missions. No telemetry event is required for this transition.

Both live states retain the mission's host lease and permit heartbeat, re-entry
and cleanup retry. Verdict authority remains the pending review bundle and its
complete submitted batch. Ordinary Browser inspection captures enter
`awaiting_walk_review` directly; they do not create a mission walk.

## Governed rollout

The ordered walk-state migration replaces the state check and every partial
live-execution index, then classifies old review rows from their immutable
roster, recorded capture run and existing walk-end receipts. A mission without
all receipts becomes `walking`; fully handed-back missions and ordinary
captures become `awaiting_walk_review`. Terminal and capture-in-progress rows
remain unchanged. Reapplying the migration does not rewrite converged rows.

The entry declares `MINIMUM_SERVING_VERSION = "next-release"`. Rehearse it on
the claimed candidate and retain the fleet-preflight receipts. The release
resolves the floor and drains older serving builds before applying the atomic
cutover through boot convergence, with the required restore point. Candidate
traffic begins only after schema convergence; the old serving build keeps its
old schema until that boundary. Merge alone never rewrites a serving database.
Upgrade clients with the carrying release; no retired-state alias remains in
current readers or writers. Release orchestration owns deployment and fleet
preflight; an item worker never applies this migration by hand.
