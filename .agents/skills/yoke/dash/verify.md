# Dash — verify

Iterate with `yoke watch pytest --impacted main --bounded`; the attached QA case is the one full run. Commit, then re-survey the actual touched files before each SHA-bound case; any tree change reruns the affected cases.

Optional review plan: select it, attach it, then run its cases.

```text
yoke workflows item-posture amend ITEM --verification-plan ID_OR_SLUG --reason TEXT
yoke qa item-plan attach --item ITEM --project P --plan-id <id> --transition reviewing-implementation --qa-phase verification
yoke qa plan materialize --item ITEM --transition NEXT_STAGE --json
yoke qa case run --requirement-id <requirement-id>
```

A requested screenshot selects `--verification-method browser-inspection` on the same amend. A capture is not a pass: submit the returned review bundle. Browser placement: `.yoke/docs/verification/browser-targets.md`.

If the completion flow has item-scoped QA, answer it before merge: attach a plan at the release stage with `--qa-phase post_deploy`, or record that nothing is observable.

```text
yoke qa post-deploy record-no-obligation --item ITEM --reason "<why no observable obligation>"
```

Selected posture adds proof: path claims cover the touched files; approval-on-done waits for the owner at the terminal transition. When every case passes, close review:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Implementation complete; verification passed"
```

Next: [merge](merge.md), or [close-out](close-out.md) when laneless.
