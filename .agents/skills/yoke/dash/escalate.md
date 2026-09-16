Escalation converts a Dash into an Issue and is reached two ways: the operator
asks for it, or execution hits a real decision boundary the operator must
settle. Those boundaries are about authority and meaning, never about size:

- the requirement is genuinely unclear and cannot be settled from the item,
  the codebase, or the operator's stored instructions;
- the outcome requires work in an additional project, which needs its own
  companion item filed there;
- the outcome requires authorization this session does not hold;
- the instruction conflicts with another requirement, and the conflict cannot
  be resolved without the operator.

None of these automatically require cancelling the Dash or filing an Issue;
they require stopping and asking. Planning, multi-file coordination, multiple
implementation slices, and sheer volume are Dash work — carry them here and do
not propose a conversion because the work is large.

Escalation files a new Issue and cancels the Dash, so it is a scope judgment
the operator owns — a deliberate exception to the kick-off-and-walk-away
default. Before drafting the proposed Issue title and findings, take `PROJECT`
from the Dash item detail and read the issue-workflow projection through
registered `workflow.execution_instruction.resolve`:

```text
yoke workflow execution-instruction resolve --workflow issue --project PROJECT
```

Apply every returned instruction, then stop Dash execution at the boundary and
present to the operator:

- the grounded findings and what the instruction turned out to require;
- the specific boundary reached, and why it cannot be settled here;
- the proposed Issue title and framing;
- that escalating cancels this Dash.

Then ask whether to escalate, and wait. Do not file the Issue, cancel the
Dash, or continue implementing past the boundary while the answer is pending.

Only after the operator explicitly agrees, run:

```text
yoke direct-workflow dash escalate ITEM \
  --issue-title "<specific title>" \
  --findings "<grounded findings and remaining outcome>"
```

The operation is idempotent: it preserves one link to the absorbing Issue
and cancels the Dash. Stop Dash execution after it succeeds and release the
work claim if the operation did not already do so.

If the operator declines escalation, follow their direction — continue,
narrow, or park the Dash — without filing an Issue.
