---
name: onboard
description: "Make a wired project execution-ready — strategy docs, execution profile, scaffold and infra Packs, hosting, environments, a gated first deploy, and seeded first work."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--project P] [--run-id RUN]"
---

# /yoke onboard

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Make a wired project execution-ready through strategy, a confirmed profile,
Packs, verified capabilities, delivery/domain registration, gated first deploy,
and queued work. Read [run-and-rows.md](run-and-rows.md) before step 1.

Arguments: --project P or mapped `yoke projects checkout-context --field slug`;
--run-id RUN resumes the known checklist (initialize only if none exists).

Wire-up belongs to `yoke setup`: missing machine/account/GitHub/project binding
stops with that terminal recovery. Harness connection is detect-only;
never install one. The web views and steers; it never invokes.
No web button runs this skill.

Checklist read is authority; the rendered local display is read-only:
never treat it as authority or edit it. Use registered adapters/function ids
and preview-first Packs; do not hand-write runtime/browser/core capability code.
Secrets enter terminal --value-stdin only, never chat; never print raw values.
Propose derived facts, ask only unknowns, and echo evidence after each write.

## Phase map — eight steps

| # | Step/home | Entry | Skip |
|---|---|---|---|
| 1 | [Strategy Conversation](strategy-conversation.md) | Wired, active run | Five accepted non-placeholder docs |
| 2 | [Derive The Execution Profile](profile-and-scaffold.md) | Strategy accepted | All steps 3–8 satisfy live predicates; otherwise rederive/reconfirm, profile not persisted |
| 3 | [Install The Scaffold Pack](profile-and-scaffold.md) | Confirmed Pack or existing-app mapping | Installed receipt; updates separate |
| 4 | [Hosting Capability](hosting-and-environments.md) | No confirmed no-host posture | No-host declaration or capability plus passing identity probe |
| 5 | [Deploy Flow/policies](hosting-and-environments.md), [verification](verification-binding.md), [governed-database.md](governed-database.md) | Scaffold; live hosting-setup=verified\|configured or deferred\|not-needed | Managed registrations/default/test binding match; or no-host delivery choice is verified as a registered merge-only default or an empty default; independent policies/test binding match; declared `migration_model` capability or a terminal `migration-model-setup` row; Packs skip individually |
| 6 | [Domain](domain-and-deploy.md) | Managed registrations or live no-host | Managed domain matches, or current no-host branch recorded `domain-setup=not-needed` |
| 7 | [Gated Infra Apply + First Deploy](domain-and-deploy.md) | Live managed host/all prior steps; no-host records terminal rows without gate | Live healthy deployment, or terminal `deferred\|not-needed` still matches the live hosting row |
| 8 | [Seed The First Work](seed-work.md) | Accepted CURRENT-PLAN, even deferred deploy | Run already recorded seeded IDs |

## Handoff

Report project/checkout/run with open rows, docs written/kept, Pack versions,
redacted capabilities, environments/flows or explicit absence, URL+smoke or
deferral, seeded refs and blockers. Required unknown/needed/blocked rows prevent
completion. /yoke steer staffs the queue; /yoke charge selects runnable work.
