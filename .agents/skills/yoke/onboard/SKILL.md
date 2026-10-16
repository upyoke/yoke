---
name: onboard
description: "Adopt a wired project's existing work, set strategy and CURRENT-PLAN, configure only what the first work needs, and hand off to steering until the first item is done."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--project P] [--run-id RUN]"
---

# /yoke onboard

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Take a wired project from its existing work to its first item done: scan
what already exists, settle strategy and CURRENT-PLAN, configure only what
the first work needs, then hand off to `/yoke steer`. Read
[run-and-rows.md](run-and-rows.md) before step 1.

Arguments: --project P or mapped `yoke projects checkout-context --field slug`;
--run-id RUN resumes the known checklist within the selected project.
Read `yoke onboard checklist get --project P`; initialize only when it reports
no saved run. A second machine reuses project choices and checks local prerequisites.

This session belongs to one project folder and never switches projects.
Outside a project folder, `yoke-global` picks or adds the project, carries
what the user wants and names the folder to open; start `/yoke onboard` in a
new session there. Settled choices from that conversation are reused, not re-asked.

Wire-up belongs to `yoke setup`: missing machine/account/GitHub/project binding
stops with that recovery. The person runs `yoke setup` in a terminal, or this
session runs `yoke setup --agent` and relays each question
(`.yoke/docs/start/agent-setup.md`). Harness connection is detect-only;
never install one. The web views and steers; it never invokes.
No web button runs this skill.

Checklist read is authority; the rendered local display is read-only:
never treat it as authority or edit it. Use registered adapters/function ids
and preview-first Packs; do not hand-write runtime/browser/core capability code.
Secrets enter terminal --value-stdin only, never chat; never print raw values.
Propose derived facts, ask only unknowns, and echo evidence after each write.

## Phase map

Steps 2–7 run only when the first work needs them. Each one the first work
does not need records its rows `deferred` with evidence naming that work,
and waits until later work needs it.

| # | Step/home | Entry | Skip |
|---|---|---|---|
| 1 | [Strategy Conversation](strategy-conversation.md) | Wired, active run | Existing work scanned; five accepted docs; first work chosen |
| 2 | [Derive The Execution Profile](profile-and-scaffold.md) | First work chosen | Saved profile covers it and matches refreshed facts |
| 3 | [Install The Scaffold Pack](profile-and-scaffold.md) | First work needs an app scaffold | Installed receipt, mapped existing app, or deferred |
| 4 | [Hosting Capability](hosting-and-environments.md) | First work needs a managed host | No-host declaration, verified capability, or deferred |
| 5 | [Deploy Flow/policies](hosting-and-environments.md), [verification](verification-binding.md), [governed-database.md](governed-database.md) | First work needs delivery, a test gate or a governed database; scaffold; live hosting-setup=verified\|configured or deferred\|not-needed | Managed registrations/default/test binding match; or no-host delivery choice is verified as a registered merge-only default or an empty default; declared `migration_model` capability or a terminal `migration-model-setup` row; each unneeded row deferred |
| 6 | [Domain](domain-and-deploy.md) | Managed registrations or live no-host | Managed domain matches, or current no-host branch recorded `domain-setup=not-needed` |
| 7 | [Gated Infra Apply + First Deploy](domain-and-deploy.md) | First work deploys to managed infrastructure | Live healthy deployment, or terminal `deferred\|not-needed` still matches the live hosting row |
| 8 | [Hand Off The First Work](first-work.md) | Accepted CURRENT-PLAN | Handoff recorded; activation is read live |

## Activation

Onboarding succeeds when the project's first meaningful item reaches
**done** under its own completion obligations. Merge alone counts only when
that item's workflow and delivery require nothing more. The checklist's
`lifecycle-readiness` row reads this from the project's items; nobody writes it.

## Handoff

Report project/checkout/run, open rows, docs written/kept, what the first work
needed and what was deferred, Pack versions, redacted capabilities,
environments/flows or explicit absence, the steering handoff and blockers.
`setup_readiness.unmet_rows` names required unknown/blocked prerequisites;
unexamined optional capabilities stay unknown.
