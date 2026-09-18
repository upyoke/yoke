Two different things stop a Dash, and only one of them files an Issue.

## Ask the question and keep the Dash

Execution reaches a decision boundary when it needs something only the operator
can settle. Those boundaries are about authority and meaning, never about size:

- the requirement is genuinely unclear and cannot be settled from the item,
  the codebase, or the operator's stored instructions;
- the outcome requires work in an additional project, which needs its own
  companion item filed there;
- the outcome requires authorization this session does not hold;
- the instruction conflicts with another requirement, and the conflict cannot
  be resolved without the operator.

None of these converts the Dash. Ask the specific unresolved question, keep the
item and its lane exactly as they are, and resume execution when the answer
arrives. Do not draft an Issue, read the issue-workflow projection, or cancel
anything — an ordinary clarification is not a workflow change, and treating it
as one throws away a lane that was about to finish the work.

State only what is actually unresolved: the grounded findings so far, the one
question, and what each answer would change. Then wait, and continue the Dash
under the answer you get.

Planning, multi-file coordination, multiple implementation slices, and sheer
volume are none of this. They are Dash work — carry them here.

## Convert the Dash into an Issue

Conversion happens two ways: the operator asks for it, or the operator agrees
to it after you named an actual structural need — the outcome genuinely
requires parallel worktrees or a generated task graph. Never propose it
because the work turned out large.

Only once conversion is on the table, take `PROJECT` from the Dash item detail
and read the issue-workflow projection through registered
`workflow.execution_instruction.resolve`:

```text
yoke workflow execution-instruction resolve --workflow issue --project PROJECT --full
```

Apply every returned instruction, then present to the operator:

- the grounded findings and what the instruction turned out to require;
- the structural need that a Dash cannot carry;
- the proposed Issue title and framing;
- that escalating cancels this Dash.

Then ask whether to convert, and wait. Do not file the Issue, cancel the Dash,
or keep implementing while the answer is pending.

Only after the operator explicitly agrees, run:

```text
yoke direct-workflow dash escalate ITEM \
  --issue-title "<specific title>" \
  --findings "<grounded findings and remaining outcome>"
```

The operation is idempotent: it preserves one link to the absorbing Issue
and cancels the Dash. Stop Dash execution after it succeeds and release the
work claim if the operation did not already do so.

If the operator declines, follow their direction — continue, narrow, or park
the Dash — without filing an Issue.
