# Onboard Step 8: Hand Off To Steering

Rows: `work-seeding`, `verification`.

Onboarding files no items. Guide the operator to write the plan as strategy
docs with `/yoke strategize`: CURRENT-PLAN, a named initiative, or several. A
new initiative starts from
`yoke strategy doc create SLUG --summary "..." --state draft --stdin`, seeded
with the headings in `steer/scope-and-authority.md`. A plan is never final;
ask the operator to approve starting the first wave once it is ready enough.

On that approval, re-read the checklist and strategy, emit the event, and
write both rows:

```text
yoke events emit --name ProjectOnboardingVerificationCompleted --kind lifecycle --type project_onboarding --source-type agent --project {project} --context '{"run_id":"{run_id}"}'
```

Follow `run.next_action` to `/yoke steer`, naming every doc the operator
approved; steering files and staffs the first wave. Steer gives each dash
its own done test and flow when filing; a dash filed without a plan is verified
by the quick command bound here. Installer, onboarding or
machine-connection work attaches the project-owned installer-campaign plan.
Review-only suites add blocking `implementation_review` plus advisory `command`.
The `lifecycle-readiness` row verifies itself when an item reaches done.
