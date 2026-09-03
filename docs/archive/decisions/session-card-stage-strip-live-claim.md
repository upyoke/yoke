# The session card stage strip reads the live claim, not status alone

## Context

The Sessions page and the steering view render one session card per
session. A card whose session holds an item work claim carries a stage
strip: one segment per stage of the item's pinned workflow version, painted
complete, active, pending, or failed. The roster projection
(`yoke_core.domain.session_item_stage_states`) is the only source of that
strip; both views render whatever it hands them.

The strip originally painted the item's `status` stage as the active one.
That is wrong for any skill whose bound segment starts on a handoff stage the
item sits on for a while. A Dash keeps status `idea` from filing until its
worker has claimed it, surveyed the touch set, and prepared its lane; the
transition to `implementing` comes after. So a card for a Dash worker deep in
execution read `idea · active`, which the operator saw on a live card and
reported: the idea phase was long done and the worker was executing.

## Decision

The active segment is derived from the pinned workflow version and the live
work claim together, with no branch on the workflow id:

- A skill binding's `from_stage_id` is the handoff the previous skill
  completed. When the session holding the item's live work claim is in that
  binding's own skill mode (`harness_sessions.mode`), the skill has taken the
  handoff: the handoff stage paints complete and the binding's first working
  stage paints active. For a Dash claimed by a session in `dash` mode this is
  `idea` complete, `implementing` active. For an Issue at `idea` claimed in
  `refine` mode it is `refining-idea` active.
- A binding with no working stage after its handoff (the Task workflow's
  single-stage `dash` segment) keeps the status-derived stage.
- Every other posture keeps the status-derived stage: an unclaimed Dash at
  `idea`, a Dash claimed by a session still in `wait` mode, an Issue mid
  implementation, and a session that filed an item and holds its claim in
  `idea` mode all paint the status stage active.
- A landed-but-open item still paints the close-out stage active; the live
  claim never overrides that.

Failure signals keyed to the active stage (a failed launch, an operational
block) attach to the derived working stage, so they land on the segment the
operator reads as current.

The holder's mode is read from the claim itself rather than from the card's
session, so a lane row on another session's claimed item shows the same
strip as the holder's card.

## Consequences

- The strip is a projection of two live facts, status plus claim posture, and
  changes when either does. A worker that stamps its mode late paints the
  status stage until it does; `/yoke dash` stamps `--mode dash` before its
  survey for exactly this reason.
- Failure signal queries live in
  `yoke_core.domain.session_item_stage_failures`; the stage-state module owns
  item selection and the active-stage derivation.
