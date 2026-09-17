# Dash phases 2–3 — survey the touch set, then isolate

## 2. Infer and survey the touch set

**Bounded discovery only.** This step exists to name candidate files, not to
read, trace, or fix them. The moment you can name the likely touch set, stop
and record the survey below, then isolate — deep reading, call-chain tracing,
and edits belong inside the worktree phase 3 creates, never here. A long
investigation that never paused to survey and isolate is a Dash that started
implementing on main.

Discover this project's source and test roots before grepping — read them from
the project rules file, or derive tracked top-level roots with
`git ls-files | cut -d/ -f1 | sort -u`. Enumerate candidates from those
resolved roots with `rg --files ... | rg '<name-or-symbol>'` before reading;
never pass optional path globs to zsh, invent a conventional source root, or
mirror a test filename into an assumed implementation path. Use imports or
symbols to find the owner. Then read only far enough to name the likely touch
set. Prefer files; use a directory only when the work genuinely spans it.

Record the survey:

```text
yoke direct-workflow dash survey ITEM --path <path> [--path <path> ...] --json
yoke direct-workflow dash survey ITEM --no-changes --json
```

Use the second, empty-intent form only for a grounded no-change outcome. The
forms are exclusive; never invent a placeholder path for a no-change Dash.

Every survey call replaces the entire stored touch set; it never widens the
previous set. Repeat every still-required path on every call. To rediscover
the live survey at path-widening time, run
`yoke direct-workflow conflict-survey status ITEM --json` — there is no
`yoke survey` command. The receipt names this as `touch_path_update="replace"`
and echoes the complete stored set.

The response's `path_sizes` carries `current_line_count`, `remaining_headroom`,
`at_or_over_limit`, `limit`, and `classification` for every path. Treat an
at/over-limit path as a pre-implementation split or alternate-home decision;
do not wait for the commit gate.

## File Budget and path claims

When `FILE_BUDGET_POLICY` is non-`optional`, persist the surveyed edit targets
and their single responsibilities plus the survey's same per-path sizing
fields under `## File Budget` through
`items.structured_field.section_upsert` before implementation. When disabled,
do not require or invent the section. When `PATH_CLAIMS_POLICY` is
non-`optional` and budget is off, the survey itself is the claim-path source.
When both are enabled, pair their enumerations. When budget is on and claims
are off, use the budget for sizing and conflict evidence without registering a
claim. When both are off, the stored instruction and survey define scope
without either artifact.

## Resolving a survey contact

For every reported survey contact, read the advisory and choose:

- proceed when the edits are independent; same-file collisions resolve at merge;
- when the decision needs holder evidence, ask an addressable holder for that
  evidence with the harness task-messaging tool (`send_message_to_thread` in
  Codex). When the holder is not addressable in the current harness, give the
  operator its session id and wait;
- when the edits are order-dependent, wait for the holding work to land
  (merge receipt, merged_at, or git ancestry — not status) and re-run the survey;
- when a directory survey was only a discovery aid, narrow it to the complete
  concrete file set before preparation, repeating every required file in the
  replacement survey;
- when an overlap cannot be decided or resolved from the surfaced evidence,
  release the work claim and present the holder, paths, and evidence to the
  operator; do not create a dependency or attestation, or continue editing
  through uncertainty;
- if the survey reveals a decision boundary — an unclear requirement, work in
  another project, missing authorization, or a conflicting requirement — stop
  and follow [`escalate.md`](escalate.md), which asks the question and keeps
  the Dash. A larger-than-expected touch set is not such a boundary.

Selected path-claim posture is a separate coverage obligation, never a remedy
for a survey contact. When effective path claims are enabled, keep the inferred
set complete and register or widen it through `claims.path.register` /
`claims.path.widen` before preparation; preparation only validates that
coverage.

Never remove a required file merely to make the survey clear.

## 3. Claim and isolate

Run this immediately after recording the survey — before reading further file
contents, tracing implementation details, or making any edit.

Prepare the item lane (a `--no-changes` survey skips creation):

```text
yoke direct-workflow worktree prepare ITEM --workflow dash --json
```

No environment override is required. Validation-surface provisioning is a
best-effort local lane convenience, not a Dash preparation gate; an HTTPS
control plane has no local capability database to inspect and skips that step
silently. Governed migration rehearsal remains the validation authority when
the instruction changes a database model.

Use the returned absolute `worktree_path` for every read, edit, test, and git
command. Keep the Cursor agent rooted on the main project checkout — do not call
`move_agent_to_root` (or otherwise remount the chat) into `.worktrees/...`. Yoke
worktrees are code lanes, not the conversation home; remounting assigns a new
Cursor conversation id and, after the lane is removed, leaves Shell stuck on a
deleted cwd (`ENOENT`). Pass an explicit live `working_directory` when Shell
would inherit a worktree or deleted path.

The preparation call reuses the item work claim already held since phase 1
(reporting `work-claim:already-owned`, or acquiring it if absent), validates
selected path-claim coverage against the survey, activates those claims, brings
the project's default branch current with the remote that tracks it, and
creates or reuses the registered worktree.

An item belonging to another project prepares its lane in THAT project's
checkout: preparation resolves the item's project machine mapping
(`yoke project register <checkout> --project-id <id>` adds a missing one) and
refuses rather than borrowing the session's repo. The work claim covers the
recorded lane; repair a wrong-repo lane with `yoke item-worktrees path-record`.
One item never gets a second lane in another repo. Work the instruction turns
out to mandate in a second project needs its own companion item filed there and
linked by an `item_dependencies` edge — a scope judgment the operator owns, so
follow [`escalate.md`](escalate.md) rather than writing into that repo from here.

Activate through the shared lifecycle interpreter:

```text
yoke lifecycle transition ITEM --from idea --to implementing --reason "Dash execution started"
```

The live `conflict_survey` gate requires a recorded, readable touch set and
re-evaluates current contacts, but an overlap does not block the transition.
The `work_claim_activation` gate verifies this session owns the item claim.
`--no-changes` skips the git lane; otherwise the item needs its worktree.

Next: [`implement.md`](implement.md).
