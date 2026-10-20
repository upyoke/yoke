# QA seeding

Attached plans supply cases. Add a requirement only for missing coverage,
at the pinned QA stage; never seed free-form smoke or e2e requirements.

```text
yoke qa requirement add --item PREFIX-N --qa-kind ac_verification --qa-phase verification --workflow-transition reviewed-implementation --requirement-source ac_derived --success-policy all-pass
```

Browser contract: [browser-seeding](browser-seeding.md).
