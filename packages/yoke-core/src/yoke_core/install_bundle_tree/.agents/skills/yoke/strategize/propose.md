# Strategize — propose and checkpoint 3

Draft only operator-selected findings: one change entry each, or zero if no
SML edit is needed. Minimal section/paragraph diff; preserve voice/structure.
Use stable file/section headers rather than line numbers.

## Mission and future concepts

MISSION is stable unless explicitly requested, a selected contradiction
identifies its issue, or the selected shift truly outgrows it. The latter needs
a minimal edit justified at mission level; weak/ambiguous drift is a flag for
operator review while lower-doc changes carry the update. Every Mission write
still needs explicit operator confirmation.

Pulled-forward primitives are now current v0; later work may own broader UX,
fan-out, authority/policy or scale. Require consuming the existing primitive,
or an exact deletion/absorption target for intentional temporary machinery.
Changes must guide what to build/not yet build and the future consumer,
rather than just moving a phrase between plan boundaries.

## LANDSCAPE editorial rules

Weave into existing related content first; rewrite the same theme instead of
appending beside it. Summarize grouped developments rather than enumerating.
Dense sections require consolidation BEFORE any addition; retire stale,
superseded and table-stakes entries. Preserve real new signal by making room.
Every net-new bullet/paragraph needs explicit justification why weaving fails
and why adding is clearer; weak justification means rewrite. Name the editorial
move in rationale. Consolidate/retire remain distinct first-class change types.

Each change: finding identity, type update/add/remove/consolidate/retire,
file/section path, current excerpt <=5 lines, FULL proposed text and
evidence-based rationale. Removal/folding is valid proposed content.
Group by file; LANDSCAPE header counts weave/update, consolidate, retire, add.
If additions dominate a flagged dense section, revisit before presentation.
Show Mission changes/flags or unchanged explicitly.

## Checkpoint 3 — before any strategy write

Present grouped exact changes/counts in plain chat; accept:
- Approve all: `cp3:approved_all`.
- Revisions: redraft/re-present ONLY affected entries until confirmed;
  `cp3:approved_revised`.
- Defer all: no strategy writes; `cp3:deferred_all`.
- Abort: entry release contract, stop the pipeline.

Return `## Proposed SML Changes` and `## Approval Status`: decision
approved/revised/deferred/aborted, approved/deferred/dropped counts and exact
lists/text. Retain deferred proposals for the audit context.

After the completed checkpoint emit SMLChangeProposed
(lifecycle/strategize/skill, INFO/completed/project) with total_changes,
approved, deferred, dropped, files_affected and mission_readonly reflecting
whether Mission edits were explicitly authorized. Aborted pipelines stay stopped.
