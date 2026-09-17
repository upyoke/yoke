---
name: onboard
description: "Make a wired project execution-ready — strategy docs, execution profile, scaffold and infra Packs, hosting, environments, a gated first deploy, and seeded first work."
argument-hint: "[--project P] [--run-id RUN]"
---

# /yoke onboard

Make an already-wired project **execution-ready** from a supported harness. The terminal wizard (`yoke onboard`) owns wire-up — machine profile, account, GitHub, project binding, review. This skill starts from strategy and derives everything else: the strategy-doc corpus, one confirmed execution profile, scaffold and infra Packs, hosting verification, hosted environment/site/flow registration or an explicit no-host route, the domain record, a gated infrastructure apply plus first deploy, and the first seeded work items.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--project P` — project slug. Default: the checkout's mapped project (`yoke projects checkout-context --field slug`).
- `--run-id RUN` — durable onboarding checklist run to resume. When omitted, initialize a new run (see Run Init And Resume below).

## Boundaries

- **Assume the wizard's output; never re-create it.** If the machine, account, GitHub connection, or project binding is missing, stop and point the operator at the `yoke onboard` terminal wizard. This skill never reimplements wire-up.
- **Harness connection is upstream and detect-only.** The skill runs inside an already-connected harness. Detect and link harnesses; never install one for the user.
- **The web views and steers; it never invokes.** The workbench's navigation Setup control renders this checklist's rows and offers this command as text for the operator to run. No web button runs this skill.
- **Checklist authority** is `yoke onboard checklist --run-id {run_id} --json`. The rendered project-local checklist view is read-only display; never treat it as authority and never edit it.
- **Sanctioned surfaces only.** Every mutation goes through registered `yoke <subcommand>` adapters / function ids — no raw DB writes, no ad hoc shell choreography. Do not hand-write project runtime, browser, or core implementation files; reusable capability code lands only through the preview-first Pack surfaces.
- **Secrets never through the chat.** Credential values go only into terminal `--value-stdin` prompts; the conversation carries redacted evidence only (identity checks, key IDs). Never print raw secret values.
- **Ask only for unknowns.** Anything derivable from strategy, the repo, or recorded settings is proposed, not asked.
- **Echo evidence after every write.** Each completed step reports what was written and where (docs written, Pack version installed, environments registered, deploy URL plus smoke result).

## Step map — read one file, at the step it governs

Execute the steps in order. Read each sub-file when its step is next; each file
carries the full procedure, recipes, and checklist row writes for its steps.


| # | Step | File | Entry | Skip |
|---|---|---|---|---|
| 1 | Strategy conversation | [strategy-conversation.md](strategy-conversation.md) | Wire-up verified; checklist run active | All five docs present with accepted, non-placeholder content |
| 2 | Derive the execution profile | [profile-and-scaffold.md](profile-and-scaffold.md) | Strategy docs accepted | Only when steps 3–8 all already satisfy their skip predicates (nothing left to apply); otherwise re-derive and re-confirm — the profile is never persisted |
| 3 | Install the scaffold Pack | [profile-and-scaffold.md](profile-and-scaffold.md) | Confirmed profile includes a scaffold Pack (an existing app maps instead of installing) | `.yoke/packs.json` receipt already records the Pack |
| 4 | Hosting capability | [hosting-and-environments.md](hosting-and-environments.md) | The project has not declared that Yoke manages no host | Declared posture is `no-yoke-managed-host`, or `aws-admin` capability present AND live identity probe passes |
| 5 | Infra Packs + verification binding + governed-database declaration; hosted registrations or no-host delivery | [hosting-and-environments.md](hosting-and-environments.md) + [verification-binding.md](verification-binding.md) + [governed-database.md](governed-database.md) | Scaffold present; branch on live `hosting-setup=verified\|configured` versus `deferred\|not-needed` | Live hosting branch matches the profile: managed registrations/default plus test binding exist, or the no-host delivery choice is verified as a registered merge-only default or an empty default; terminal rows and independent Project Structure work match; the governed-database answer is recorded as a declared `migration_model` capability or a terminal `migration-model-setup` row; recorded Packs skip individually |
| 6 | Domain | [domain-and-deploy.md](domain-and-deploy.md) | Hosted environments registered, or live hosting row is `deferred\|not-needed` | Live managed-host domain exists, or the current no-host branch recorded `domain-setup=not-needed` |
| 7 | Gated infra apply + first deploy | [domain-and-deploy.md](domain-and-deploy.md) | Live hosting row is `verified\|configured` and every earlier managed-host step is satisfied; no-host branch records its terminal result without entering the gate | Managed deploy is live and healthy, or terminal `deferred\|not-needed` still matches the live hosting row |
| 8 | Seed the first work | [seed-work.md](seed-work.md) | CURRENT-PLAN exists (a deferred deploy does not block seeding) | This run already recorded seeded items on its checklist row |

Run initialization, resume, the two pacing gates, and the row-write/failure-floor
contract are in [`run-and-rows.md`](run-and-rows.md) — read it before step 1.

## Handoff

After step 8, finish with a concise summary: project slug and checkout, checklist run id with open/blocked rows, strategy docs written, Packs installed with versions, capabilities verified (redacted), environments and flows registered or explicitly absent, deploy URL plus smoke result (or the explicit deferral), seeded item ids, and remaining blockers. Do not claim onboarding is complete while any required row is `unknown`, `needed`, or `blocked`. Point the operator at `/yoke do` to start the build loop — the loop itself is outside this skill.
