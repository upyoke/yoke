# Onboard Steps 2–3: Profile And Scaffold

Reuse the saved profile unless `profile_changed`. Choose for the first work:

- Delivery: persistent environment (needs hosting), merge-only, or no default.
- Tests: surveyed command, scaffold suite, review-only, attested no-tests, or stop.
- Database: declare now, attach later, none.
- Packs and their tool prerequisites; none for an unused host.

Stop 1: no writes before the operator confirms. Then save it and write `human-interview`:

```text
yoke onboard checklist --run-id {run_id} --profile-file /tmp/confirmed-profile.json
```

Step 3: map an existing app instead of forcing conflicts. Preview without
`--apply`, apply, commit the files.

```text
yoke packs get webapp-scaffold {checkout} --project {project} --apply
```
