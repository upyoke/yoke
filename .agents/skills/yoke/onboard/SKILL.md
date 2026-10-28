---
name: onboard
description: "Adopt a wired project's existing work, set strategy and CURRENT-PLAN, configure only what the first work needs, and hand off to steering until the first item is done."
argument-hint: "[--project P] [--run-id RUN]"
---

# /yoke onboard

Unless it just passed, check the session; relay each failure's fix, rerun, and
continue when all pass or only passable warnings remain. A harness CLI sign-in
WARN allows onboarding: tell the person that worker launches need the CLI and
its sign-in, and give the warning's install or login step for later. A session
posture WARN needs the person to confirm the setting named in the warning:

```text
yoke doctor run --session
```

Never switch projects or install a harness. Missing wire-up: `yoke setup`.
Secrets go through `--value-stdin` only. The checklist read is authority; never
edit its rendered local view.

Phase map: read [run-and-rows.md](run-and-rows.md); follow `run.next_action`. Steps 2–7 run only for what the
first work needs; otherwise write their rows `deferred`.

1. [strategy-conversation.md](strategy-conversation.md)
2. Profile, scaffold: [profile-and-scaffold.md](profile-and-scaffold.md)
3. Hosting, delivery: [hosting-and-environments.md](hosting-and-environments.md)
4. Domain, infra: [domain-and-deploy.md](domain-and-deploy.md)
5. Handoff: [first-work.md](first-work.md)
