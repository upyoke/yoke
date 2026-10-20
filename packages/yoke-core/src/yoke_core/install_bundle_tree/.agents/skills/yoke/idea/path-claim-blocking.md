# Idea — Claim Conflict Resolution

Never drop a required file.

```text
yoke claims path coordination-decision-build --item PREFIX-N --conflicting-claim <claim-id> --paths <shared-paths>
```

Independent edits: `coordination_only` with a verifiable rationale. Ordered
edits: `activation` with `fact:merged`. Unclear: ask. Last resort:
`yoke items block`, never `status=blocked`. Then re-register.

```text
yoke items dependency add <candidate-ref> <other-ref> idea --gate-point coordination_only --rationale "<why independent>"
```
