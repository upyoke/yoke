# Onboard Step 8: Hand Off To Steering

Rows: `work-seeding`, `verification`.

Onboarding files no items. Re-read the checklist and strategy, emit the event,
and write both rows:

```text
yoke events emit --name ProjectOnboardingVerificationCompleted --kind lifecycle --type project_onboarding --source-type agent --project {project} --context '{"run_id":"{run_id}"}'
```

Follow `run.next_action` to `/yoke steer CURRENT-PLAN`. Steer gives each dash
its own done test, flow and QA plan when filing. Installer, onboarding or
machine-connection work attaches the project-owned installer-campaign plan.
Review-only suites add blocking `implementation_review` plus advisory `command`.
The `lifecycle-readiness` row verifies itself when an item reaches done.
