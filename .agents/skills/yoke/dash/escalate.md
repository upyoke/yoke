Halt as soon as the required outcome needs crafted acceptance criteria,
substantial design, durable multi-file coordination, or multiple delivery
slices. Escalation files a new Issue and cancels the Dash, so it is a scope
judgment the operator owns — a deliberate exception to the
kick-off-and-walk-away default. Before drafting the proposed Issue title and
findings, take `PROJECT` from the Dash item detail and read the issue-workflow
projection through registered `workflow.execution_instruction.resolve`:

```text
yoke workflow execution-instruction resolve --workflow issue --project PROJECT
```

Apply every returned instruction, then stop Dash execution at the trigger and
present to the operator:

- the grounded findings and what the instruction turned out to require;
- the remaining outcome that is no longer instruction-sized;
- the proposed Issue title and framing;
- that escalating cancels this Dash.

Then ask whether to escalate, and wait. Do not file the Issue, cancel the
Dash, or continue implementing past the trigger while the answer is pending.

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
