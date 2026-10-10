# Conduct — every exit

Run after SUCCESS/HALTED/no-chain/explicit simulation bypass. Resolve cleanup
against inherited MAIN_ROOT, not the linked lane's rev-parse toplevel. Protect
all unfinished task code and custody.

## Owned temp and generated-view cleanup

List only known Yoke helper patterns, null-safe in bash/zsh:

```text
_yoke_dir="${MAIN_ROOT}/data"
find "$_yoke_dir" -maxdepth 1 -type f -name 'BOARD.md.board.*' -print
```

_yoke_dir is the verified owning-main legacy temp directory, not DB authority.
Other known BOARD.md.lock/BOARD.md.reg_*/BOARD.md.ts artifacts require the same
owner/orphan check. Missing paths no-op. Remove only confirmed orphaned
Yoke-managed temporary files; never delete a live helper's lock or arbitrary
matching user file. Report exact removed paths. Avoid unmatched shell globs.

Generated .yoke/BOARD.md is untracked and must never be staged/committed. If its
index is unmerged, normalize only this generated-view index entry; no tracked
checkout/clean or broad deletion. Capture current evidence first:

```text
git -C {MAIN_ROOT} status --porcelain -- .yoke/BOARD.md
git -C {MAIN_ROOT} reset --quiet HEAD -- .yoke/BOARD.md
git -C {MAIN_ROOT} status --porcelain -- data/
git -C {MAIN_ROOT} log origin/main..main --oneline
```

Index normalization only when that exact generated entry needs it. Report any
remaining main artifacts/unpushed history; never push worker bookkeeping by
hand or hide a cleanup failure. Legacy root DB files stop for investigation.

## Outcome and custody

Print CONDUCT_RESULT: SUCCESS|HALTED, actual per-task state/attempts/candidate,
remaining blocked/not-started tasks and exact next action. SUCCESS for a
no-chain/bypass leg is not parent completion. Refresh item and use
[the shared handoff recipe](../shared/stage-handoff.md) for its current binding.
Conduct does not merge, close the issue, remove lanes or mark done.

Wrong-epic body, missing-epic body and _epic_ref lost between dispatches remain
explicit, with the returned code/message, intended/attested refs and recovery.
Do not collapse identity failure to a generic gap. Retain uncertain-write ids
and readback recipe; do not repeat the persistence write to get another receipt.

At verified through-stage handoff release only the parent claim still held,
with truthful handoff reason, then verify holder-list. A release failure keeps
the handoff incomplete; no already-released double write. Each task closeout
owns its exact task claim release. A halted leg first checkpoints Progress Log
and names its actual ownership handoff/recovery; never label unfinished release
reason completed or release merely to send a report. If custody must remain
for a current mandate, retain it and record the named wait instead.
