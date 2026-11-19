# Dash — verify

A post-deploy case names where its evidence lives: Command for controller evidence, a mission with no host to explore on the controller, a test machine with `fresh-host` for clean installs.

Commit, then re-survey the actual touched files before each SHA-bound case; any tree change reruns the affected cases.

Review plan: a plan chosen at filing (the project's `registered-command-quick` default, or `--verification-plan`) is already attached at `reviewing-implementation` (`yoke workflows item get ITEM --json` shows it under `workflow_posture.verification`); go straight to `yoke qa plan materialize`. Otherwise select one with an amend, attach it by hand, then run its cases.

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
