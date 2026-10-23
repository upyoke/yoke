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

If `yoke items get ITEM post_deploy_qa` says unanswered, answer before merge with one of the two commands it names: attach a plan at the release stage with `--qa-phase post_deploy`, or record that nothing is observable.

Selected posture: path claims cover touched files; approval-on-done waits for the owner. When cases pass, a laned item runs the landing check. It lists every landing blocker with its recovery and changes nothing:

```text
yoke merge item ITEM --check --result "<result>" --verification "<proof>"
```

Fix every blocker, then follow [merge](merge.md). The merge itself moves the item into review. A laneless item transitions instead:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Implementation complete; verification passed"
```

Laneless next: [close-out](close-out.md).
