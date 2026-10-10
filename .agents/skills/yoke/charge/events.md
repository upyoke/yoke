# Charge decision events

`FrontierComputed` is engine-owned on every frontier computation.
Emit `ChargeDecisionMade` once at each terminal decision below through
`yoke events emit`; read its help for context/subject flags.

```sh
yoke events emit --name ChargeDecisionMade --kind lifecycle --type charge --source-type skill --severity INFO --outcome skipped --context '{"item_id":"","adapter":"","dispatched":false,"reason":"dry_run","project":"P"}'
```

Fill JSON from the observed schedule/decision, preserving these branch fields:

| Decision reason | Outcome | Item subject | Context |
|---|---|---|---|
| no_runnable_items, dry_run | skipped | none | empty item_id/adapter, dispatched=false, reason, project |
| requested_item_unavailable | skipped | requested public ref | empty adapter, dispatched=false, reason, target_bucket, project |
| operator_cancelled | skipped | selected public ref if any | next_step, adapter, dispatched=false, reason, project |
| wait_encountered | skipped | selected public ref | next_step=wait, adapter, dispatched=false, reason, project |
| dispatched | completed | dispatched public ref | next_step, adapter, dispatched=true, reason, project |

For unavailable targets, `target_bucket` is blocked, frozen or not_found.
Pass `--item PREFIX-N` for a present subject; never substitute an internal id.
Cancellation without a selection keeps selected fields empty. The example is
one dry-run payload, not an extra event to emit on other exits.
