# Steer — choose the level

JUNIOR: mechanical, small bug, docs. INTERN: trivial and specified. PRINCIPAL:
very complex. Otherwise omit `--level`. Item-bound `--level` overrides every
stage. Never pick the machine or surface.

```text
yoke session-control launch create --project P --item PREFIX-N --level JUNIOR --level-reason "well-specified text change" --idempotency-key K
```

## Restaff ladder

1. First failure: the same worker fixes it once.
2. Second failure or a spec misunderstanding: one level up.
3. Only mechanical work left: one level down.
4. PRINCIPAL fails or no capacity: ask the operator.
