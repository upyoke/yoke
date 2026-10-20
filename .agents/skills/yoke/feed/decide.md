# Feed — Decide (analysis only)

First match: `refresh_only` (only graph stale), `sharpen_frontier` (vague
work; recommend only), `materialize_new` (frontier empty, ground stable),
else `leave_in_sml` with a reason. `--no-new-items` blocks creates and splits.

| Class | Gate | Satisfaction |
|---|---|---|
| coding_order | activation | status:done |
| validation_before_start | activation | status:implemented |
| merge_order | integration | fact:merged |
| deployment_before_consume | where use begins | fact:deployed:<env> |
| closeout | closure | status:done |

Next: [materialize.md](materialize.md).
