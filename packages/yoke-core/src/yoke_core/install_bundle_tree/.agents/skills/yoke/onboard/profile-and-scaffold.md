# Onboard Steps 2–3: Profile And Scaffold

Rows: `human-interview`; step 3 `scaffold-install`, `documentation-context-setup`.

Reuse the saved profile unless `profile_changed`. The profile is a free-form,
non-empty JSON object; keys and values are examples, not fixed options.
For example: `{"tests": "npm test", "database": "none"}`. Confirm choices for the first work:

- Delivery: persistent environment (needs hosting), merge-only, or no default.
- Tests: surveyed command, scaffold suite, review-only, attested no-tests, or stop.
- Database: declare now, attach later, none.
- Packs and their tool prerequisites; none for an unused host.

Stop 1: no writes before the operator confirms. An undecided box writes
`human-interview=blocked`. Then save it and write `human-interview`:

```text
yoke onboard checklist --run-id {run_id} --profile-file /tmp/confirmed-profile.json
```

Step 3: map an existing app instead of forcing conflicts. Preview without
`--apply`, apply, commit the files. A Pack already in `.yoke/packs.json` is
verified, not reinstalled. Use `--allow-missing-tools` only when the confirmed
profile asks for it.

```text
yoke packs get webapp-scaffold {checkout} --project {project} --apply
```
