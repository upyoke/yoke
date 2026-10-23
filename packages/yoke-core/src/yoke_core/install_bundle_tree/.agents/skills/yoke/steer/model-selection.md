# Choose the level

JUNIOR: mechanical, small bugs, docs. INTERN: trivial, specified. PRINCIPAL:
very complex. Otherwise omit `--level`. Item-bound `--level` overrides stages.
Never pick machine or surface.
PRINCIPAL launches and restaff require explicit operator approval: they consume far more tokens.

```text
yoke session-control launch create --project P --item PREFIX-N --level JUNIOR --level-reason "specified docs" --idempotency-key K
```

## Restaff

1. First failure: same worker fixes once.
2. Second failure or misunderstood spec: one level up.
3. Mechanical work left: one level down.
4. PRINCIPAL fails or no capacity: ask the operator.

Change running levels only via
[restaff](worker-lifecycle.md#restaff-on-a-different-model).
