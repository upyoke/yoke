# Yoke — Architecture Overview

This contributor orientation separates architecture intent from live authority.
Read the current item, immutable workflow, registered command and harness
manifest before relying on a capability or changing state.

## Purpose and operating model

Yoke provides a software-delivery operating layer: operators make decisions,
agents execute assigned work, and Postgres retains claims, workflow state and
linked QA/delivery evidence across session loss. It uses the same delivery
system for its own development. Software delivery is its first proving ground
for broader company operations: a shared clearinghouse for incoming work,
participants, approvals, artifacts and outcomes.

The Strategic Markdown Layer holds `MISSION` (purpose), `LANDSCAPE`
(source-backed external research), `VISION` (chosen future and canonical visual),
`MASTER-PLAN` (evolving strategy) and its current execution plan. These are
`strategy_docs` rows; `.yoke/strategy/` contains gitignored rendered views.
Operational facts below that boundary belong to typed database records.

The main strategic paths are `/yoke steer` (staff work from strategy),
`/yoke strategize` (guided research/synthesis), `/yoke feed` (frontier facts and
materialization) and `/yoke charge` (rank and dispatch the active frontier).
Their skill phase maps own checkpoints, staffing and execution; narrower item
skills are downstream adapters. Read [frontier behavior](public/reference/charge-frontier.md).

Workflows can mix deterministic services, bounded structured judgment and
open-ended agent execution. Prefer the cheapest sufficient executor. Future
operational expansion should preserve one causal record of intent,
participants, decisions, evidence, overrides and effects rather than infer
important actions after they happen or wrap every domain in a new registry.

## Authority and workflow execution

The connected Postgres authority is the source of truth. Use registered
`yoke <subcommand>` operations and typed function calls; diagnostic SQL uses
`yoke db read`. Never construct a DB file path or treat a linked worktree as a
control plane. [Function authority](public/reference/db-reference/functions.md)
defines envelope and permission/claim contracts.

An item's immutable workflow/version pin owns stages, gates, policies, entry
surfaces and half-open skill bindings. Inspect `yoke workflows item get PREFIX-N`
and its named `yoke workflows version get WORKFLOW VERSION`. The live binding
selects the skill; names or copied stage sequences do not. A skill autonomously
executes its authorized segment with its declared human decisions, QA gates,
retry bounds and handoffs. At a binding boundary enter the next skill freshly.
[Lifecycle reference](public/reference/lifecycle.md) owns the transition contract.

One item belongs to one deployment project. A contract consumed by another
project requires linked companion work and exact-candidate consumer evidence.
Items bind their deployment project through integer `items.project_id`;
`projects.slug` is a resolved display value, and public prefixes provide context.
Items use stable integer `items.id` and project-local `project_sequence`
for `PREFIX-N`; resolve the reference before using an item id or GitHub issue.

The rendered item `body` is virtual, composed from structured fields and
sections. Read `yoke items get PREFIX-N body`; use registered structured writes.
Session checkpoints belong in Progress Log, not generated task-graph fields on
a workflow with no children. `.yoke/BOARD.md` is a generated view; rebuild it
explicitly with `yoke board rebuild` (`--print` / `--print-only`). Never edit it
or rendered strategy views as authoritative content. Board appearance and scope
are governed by `project-policy.settings.board`, not the generated view.

## Project adoption and reusable capabilities

Product adoption starts with `yoke setup`, project create/import/install and
`/yoke onboard`. The phase owners survey strategy and actual execution posture,
install Packs, verify hosting, register environments/flows, execute the gated
first delivery and seed work with evidence. GitHub/CI/hosting settings and
credentials use Yoke-owned previews and resolvers, not ad hoc bootstrap scripts.

Reusable capability behavior ships in immutable versioned `packs/<slug>/`
bundles with explicit files, dependencies, settings, docs and verification.
Project-only behavior stays with the project. Installed Pack files belong to
the project; its baseline permits a previewed three-way update. Configuration
belongs to DB capabilities/settings or project-local policy, never Pack source.

Project Structure declares architecture, areas/mappings, ownership/test roots,
integration targets, context routing, hosting/verification posture and delivery
defaults. Descriptive verification profiles do not execute a gate: immutable
registered QA cases do. Explicit operator no-tests attestation is distinct from
missing or failing tests. [Projects and flows](public/reference/db-reference/projects-and-flows.md)
and [test setup](install-onboard-archetypes/test-setup.md) own details.

Each project uses the same registry/capability machinery; a literal slug does
not unlock special behavior. GitHub automation uses the verified App repository
binding and short-lived tokens. `github_sync_mode=disabled` suppresses issue
mirroring independently of connected merge/CI gates. Capability-owned secrets
stay behind their resolvers; machine-local AWS/SSH material is not ambient shell
authority. Broken authorization refuses with recovery; transient provider
unavailability remains retryable. [GitHub connections](github-connections.md)
and [GitHub sync](public/reference/github-sync.md) define these boundaries.

## Harnesses and agent roles

Yoke's state, approvals and workflow semantics are harness-neutral. Installed
release manifests under `runtime/harness/{claude,codex,cursor}/manifest.json`
define supported surfaces, identity, events, launch/wake primitives and explicit
limitations. Supported paths derive from the shared registry plus the manifest;
they are not caller self-reports. Native instructions and skills load through
[discovery](public/reference/harness-discovery.md); the [bootstrap contract](harness-bootstrap.md)
defines startup trust, identity and progressive command/packet discovery.

Canonical bodies in `runtime/agents/` render through harness adapters; edit the
canonical source, render, then sync the install bundle. Models, effort, tools,
turn bounds and dispatch contracts come from the current role source, manifest
and execution-level selection, not an overview's fixed table. See
[harness substrate](harness-substrate.md), [adapter contract](harness-adapter-template.md)
and [execution levels](public/reference/session-level-routing.md).

| Role | Responsibility |
|---|---|
| Product Manager | Convert rough ideas into structured item specifications. |
| Product Designer | Derive UX/UI specifications where the item needs design. |
| Architect | Plan session-sized tasks, exact interfaces and lane assignments. |
| Engineer | Implement assigned code, tests and documentation; commit changes. |
| Tester | Verify implementation against artifacts without modifying code. |
| QA Walker | Explore one declared mission, return findings or a precise human gate; main owns verdict. |
| Simulator | Trace plan/integration paths across tasks and return gaps. |
| Boss | Apply structured quality gates to specifications and plans. |

Shepherd and Conduct are orchestration skills. Their current phase/dispatch
contracts own staffing, gates, attempt ceilings and return boundaries. Claim the
item before its survey, prepare/reuse its registered lane, and use the exact
lane for reads, edits and tests. Scope, budget and physical path claims are
independent. Resolve overlaps through coordination/dependencies; claims do not
remove required scope. Exact interface contracts prevent integration gaps;
session-sized tasks must fit their declared execution budget. See
[lanes and claims](public/reference/agent-rules/lanes-and-claims.md).

## Persistent evidence and delivery

Items, epic tasks, universal `item_worktrees`, dispatch chains, QA requirements/
runs/artifacts, progress notes, simulations, approvals, flows and concrete runs
are linked durable facts. Task queues reference lane identity; branch/path facts
belong to the lane; dispatch chains join it through `item_worktree_id`.
Reviews and simulation receipts live in QA records, not
conversation claims. Native dispatch freshness and dependency reads govern
execution. Registered commands return the facts needed at the boundary, with
explicit full-depth reads when necessary.

Verification runs through the project's declared binding and method: Command,
Browser, inspection or mission. Record real pass/fail/pending/waived evidence,
not inferred success. Local checks are bounded iterations; attached immutable
QA is the complete execution. Exact-candidate evidence must survive later
changes or be rerun. [QA](public/qa.md) and
[verification rules](public/reference/agent-rules/verification.md) own admission,
CI continuation and failure responsibility.

Merge and delivery remain separate. Queue-declared projects use their protected
merge-group gate. A push is not release authority. Runs take no claim: a run
occupies its target servers until its QA settles; flows are immutable referenced definitions,
run ids are executions, and the hosted flow owns exact commits/artifacts,
environment proof and promotion. Retain history when disabling definitions.
Project migration models govern data transforms: permanent ordered entries,
restore points, item rehearsal and all-live-fleet release evidence; boot converges
and applies fail-hard. [Delivery rules](public/reference/agent-rules/delivery.md),
[database rules](public/reference/agent-rules/databases.md) and
[fleet rehearsal](public/reference/db-reference/migration-model-fleet.md) own
operation depth.

## Hooks, telemetry and learning

Harness-native hooks enter through Python-owned `yoke hook evaluate <event>`.
Client-local guards and serving policies compose with any deny winning; hooks
do not substitute for lifecycle/claim authority. See [hooks](hooks.md) for exact
transport, deadline, orientation, trust, timing and message-settlement contracts,
and [parity](hook-parity-map.md) before assuming equivalent native events.

The unified `events` ledger records structured tool/session/workflow/audit facts
with registry ownership and severity gating. Context identities and emitter
source are separate from semantic `event_kind`. Use [event contract](event-contract.md),
[event catalog](event-catalog.md), [logging standard](structured-logging-standard.md)
and [isolation rules](event-contract/isolation-and-querying.md). Test capture or
explicit test authority prevents live-ledger contamination; legitimate smoke
lineage is retained. Telemetry availability, missing observations and timing
coverage never decide operational correctness or prove zero activity.

Ouroboros turns observations into durable learning: field notes and role
reflection feed `ouroboros_entries`; `/yoke curate` clusters/promotes/file work;
`/yoke doctor` checks declared applicability and reports pass, fail or N/A with
reason; `/yoke simulate --system` checks source-wide consistency behind its
source-checkout guard. Project-local checks under `.yoke/doctor/` join the same
report. Reflection blocks use their role contract and capture owner rather
than an invented logging format. Source simulation depth is
[source-dev/system-simulation.md](source-dev/system-simulation.md).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Repository boundaries

| Path | Owner/purpose |
|---|---|
| `packages/yoke-core/` | Domain, API, DB, engines and contributor tools. |
| `packages/yoke-cli/` | Installed CLI, typed adapters and transport. |
| `packages/yoke-contracts/` | Shared interface, event and policy contracts. |
| `packages/yoke-harness/` | Installable hook and browser support. |
| `runtime/agents/`, `runtime/harness/` | Canonical roles, manifests and rendered adapters. |
| `runtime/api/`, `runtime/browser_runtime/`, `tests/` | API/browser/boundary verification. |
| `.agents/skills/yoke/` | Canonical situational skill knowledge. |
| `packs/` | Immutable reusable capability bundles. |
| `packaging/` | Pre-runtime installer and distribution metadata. |
| `docs/`, `.yoke/` | Public/source references and project policy/generated views. |
| `.github/workflows/` | CI and hosted release execution. |

Project code conventions and naming come from `AGENTS.md` and its operation
homes. Stateful launchers/helpers are Python-owned; Git/external tooling remains
command-shaped. JSON/YAML helpers live in `yoke_core.domain.json_helper` and
`yaml_helper`. Read the [source-dev doctrine](source-dev-doctrine.md) before
source verification, render, release, preflight or cleanup.
