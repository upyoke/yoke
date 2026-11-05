---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


Apply the plan-mode guard, then read `{subcommand}/SKILL.md` and pass the remaining arguments. Unknown: [help](help/SKILL.md).

<!-- BEGIN GENERATED: skill-registry -->
Operator: `/yoke blitz` · `/yoke charge` · `/yoke conduct` · `/yoke curate` · `/yoke dash` · `/yoke doctor` · `/yoke feed` · `/yoke help` · `/yoke idea` · `/yoke implement` · `/yoke models` · `/yoke onboard` · `/yoke polish` · `/yoke refine` · `/yoke resync` · `/yoke shepherd` · `/yoke simulate` · `/yoke steer` · `/yoke strategize` · `/yoke usher` · `/yoke wrapup`

Internal: [amend](amend/SKILL.md) · [approve](approve/SKILL.md) · [implementing](implement/implementing/SKILL.md)

**Plan-mode guard.** Exit plan mode before `/yoke blitz` · `/yoke conduct` · `/yoke dash` · `/yoke implement` · `/yoke polish` · `/yoke usher`, before an `/yoke idea` write or after `/yoke refine` Gate 0 (call `ExitPlanMode` when available, then say `Plan mode auto-exited — Yoke work item is the plan.`); every other step preserves plan mode.
<!-- END GENERATED: skill-registry -->
