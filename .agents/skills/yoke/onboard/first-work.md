# Onboard Step 8: Hand Off The First Work

Onboarding files no items. CURRENT-PLAN's first outcome names its done test,
the work it continues, its flow and QA plan. Follow `run.next_action` to
`/yoke steer CURRENT-PLAN`; attach the plan before staffing:

```text
yoke qa item-plan attach --item {ITEM} --project {project} --plan-id {plan_id} --transition reviewing-implementation --qa-phase verification
```

Review-only suites add blocking `implementation_review` plus advisory `command`.
Activation is `lifecycle-readiness` reading verified.
