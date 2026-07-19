# Deploy Checklist: Yoke

Run through before activating deploy flows for a new environment.

- [ ] Project capabilities/settings are populated in the Yoke DB.
- [ ] Deployment flows name the intended target environment.
- [ ] Provider credentials resolve through capabilities only (never
      ambient shell).
- [ ] Smoke checks are recorded as deployment or QA evidence.

- [ ] The intended source commit is on `main`, and `stage` contains the same
      Yoke content before an attended dual-environment release.
- [ ] The selected active flow comes from `.yoke/deployment-flows.json` and
      names the exact target environment; disabled historical flows are not
      reused.
- [ ] Focused tests, `yoke agents render check`, the install-bundle drift check,
      and the Atlas render check pass on the exact release commit.
- [ ] Any governed database migration has completed rehearsal, backup, apply,
      verification, and `migration_audit` evidence before delivery.
- [ ] The release bridge records a unique dispatch correlation and resolves the
      exact Yoke commit to an immutable annotated release tag.
- [ ] The wheel and server-image factories succeed, and their artifacts are
      signed for that exact tag and source commit.
- [ ] The target Platform promoter succeeds with the exact wheel and image pin.
- [ ] The Yoke deployment run completes, `yoke status` reaches the target, the
      hosted organization UI works, and the target package index is readable.
