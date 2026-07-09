---
name: block
description: "Mark a backlog item as blocked while preserving its lifecycle status."
argument-hint: "YOK-N \"<reason>\""
---

# /yoke block YOK-N "<reason>"

Mark a backlog item as blocked. Blocking sets the item-level
`items.blocked` flag to `1` and records the operator-supplied reason in
`items.blocked_reason`, **without changing the lifecycle `status`**. The
item retains its real status (e.g. `implementing`, `refined-idea`) and
returns to its normal section once `/yoke unblock` clears the flag.

This is the operator-friendly entry point for the flag-driven blocked
model. Item-level `blocked` is unrelated to
`path_claims.state='blocked'` — the latter is a coordination state on a
single path-claim row and is owned by the path-claim activation flow,
not by this skill.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `YOK-N` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `<reason>` — Operator-supplied reason for the block. Quoted because it
  is typically a sentence. Stored verbatim in `items.blocked_reason` and
  surfaced in the rendered body's `## Block` section, the
  `/yoke do` decision-engine escalate context, and the rendered
  blocked details.

## Steps

1. **Parse the ID and reason.** Extract the numeric part of the argument
   (strip `YOK-` prefix if present, strip leading zeros). Reason is the
   remaining quoted argument.

2. **Read the backlog item.**
   ```bash
   STATUS=$(yoke items get {N} status)
   BLOCKED=$(yoke items get {N} blocked)
   ```
   If `STATUS` is empty (item not in DB), stop with error:
   > Item YOK-{N} not found.

3. **Reject done items.** If `STATUS` is `done`, stop with error:
   > Cannot block a done item.

   Done items are complete and should not be blocked. If you need to
   reopen a done item, advance it back into the appropriate in-flight
   status first.

4. **Check if already blocked.** If `BLOCKED` is `true`, continue to
   step 5 so the operator-supplied reason replaces the recorded reason.
   Use this note in the final report:
   > YOK-{N} was already blocked. Updated the recorded reason.

5. **Set `blocked=true` and record the reason via the canonical adapter.**
   Use the wrapped `items.scalar.update` adapter once for `blocked` and
   once for `blocked_reason`. Each call syncs the GitHub `blocked`
   label best-effort and rebuilds the board through the shared mutation
   path.

   ```bash
   yoke items scalar update YOK-{N} --field blocked --value true
   yoke items scalar update YOK-{N} --field blocked_reason --value "<reason>"
   ```

   The adapter prints the result payload on success.
   GitHub label-sync warnings surface as `warning: github_sync_degraded`
   lines on stderr; the block itself still succeeded when exit code is
   0. If the second write (reason) fails after the first (flag)
   succeeds, rerun the `blocked_reason` command after addressing the
   reported error.

6. **Commit.**
   ```bash
   git diff --cached --quiet || git commit -m "YOK-{N}: block - <reason>"
   ```

7. **Report.**
   > **YOK-{N}** ({title}): blocked
   >
   > Reason: {reason}
   >
   > The item retains its `{STATUS}` status but is hidden from active
   > dispatch. To unblock: `/yoke unblock YOK-{N}`.

## Notes

- Blocking does **not** change the item's lifecycle `status`. The item
  keeps `implementing` / `refined-idea` / etc. and returns to its normal
  board section as soon as `/yoke unblock` clears the flag.
- The done-transition cleanup (run when a status flips to `done`) clears
  `blocked` and `blocked_reason` automatically. Operators should not
  block an item that is already on its way to done.
- The GitHub `blocked` label is added to the linked issue as a
  best-effort side effect; if the label sync fails, the local block
  still succeeds. Run `/yoke resync` to repair label drift later.
- Idea-time path-claim conflicts that cannot be represented as a
  structured `path_claims` row (the rare last-resort fallback) also
  reach for this flag through `/yoke idea`. See
  `.agents/skills/yoke/idea/path-claim-blocking.md` for the protocol.
