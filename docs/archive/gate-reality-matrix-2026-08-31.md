# Gate reality matrix (2026-08-31)

> Archived 2026-09-02 from the `GATE-REALITY-MATRIX` strategy document (now archived in the control plane). A point-in-time, read-only audit of every workflow definition, gate, posture knob, and implicit engine policy against the project reality ladder, taken as the opening artifact for the CURRENT-PLAN design-queue item 2 session. Workflow version ids and gate behavior are as they stood on 2026-08-31; nothing here is maintained.


Opening artifact for the CURRENT-PLAN item-2 design session (operator ruling 2026-08-31). Read-only archaeology of every workflow, gate, posture knob, and implicit engine policy against the project reality ladder. No code was changed; no follow-up items were filed. The design session disposes every gap.

Authority for this sweep: live `workflows.definition.get` / `workflows.version.get` / `workflows.mechanics.get` on the prod control plane (2026-08-31), plus engine enforcement sites in this checkout. Where the two disagree, the engine is what actually happens.

## Evaluation criteria (CURRENT-PLAN working principles)

Operator-settled first, last, and the two named as settled in the 2026-08-31 steering dialogue:

1. **Done needs a standard, not a human.** The human authors the standard once; machines attest instances. Attention batches at the release boundary, not per item.
2. **Declared means enforced.** A declared capability's obligations are enforced as declared. When a rung fails operationally the gate blocks loudly. The remedy is deliberately undeclaring the capability. Silent runtime degradation never happens.
3. **Gates name obligations; capabilities choose satisfiers; items record the rung.** Each gate carries an ordered satisfier ladder. The project's capability registry (plus derived facts such as remote-present and test-command-declared) picks the highest reachable rung at transition time. The item stamps which rung satisfied it. One immutable workflow definition serves every project shape; the ladder is data.
4. **Releases batch attention.** Items flow to done unattended on the delegated standard; the release groups them; QA attaches per scope (item = piece proof, release = together-proof); one human approval at the deployment run covers the group.
5. **A floor "task" workflow** (idea → implementing → done — a strict subset of the shared stage vocabulary, never divergent statuses, per operator 2026-08-31; no lanes, no QA case, no merge boundary) serves folder-only and non-code work. Outward actions use the approvals primitive as their done-gate.
6. **Capability offers land at the moment of need**, not in onboarding interrogations.

Score every cell against those six. A cell that proceeds on a lower rung than the intended satisfier is a gap. A cell that reports green while the obligation did not happen is a silent lie (worst). A cell that hard-walls a lower rung that should have a weaker satisfier is a hard wall (second). An honest named refusal that could degrade to a lower rung is third.

## Reality ladder (columns)

| Id | Rung | Meaning |
|---|---|---|
| F0 | bare folder (no git) | A directory on disk. No repository. Yoke may be installed; git has not been initialized in the project. |
| F1 | git-only | Local git repo, default branch, worktrees possible. No remote. No GitHub. |
| F2 | git+remote+GitHub App | Origin remote plus GitHub App bind (issues/PRs possible). No CI workflow declared. |
| F3 | +CI workflow | `ci_workflow_file` capability; Actions (and optionally `merge_queue`) reachable. |
| F4 | +environments+hosting+DB | Registered environments, hosting, deployment flows, and (when relevant) `migration_model`. |
| F5 | full stack | F4 plus the rest of the product surface (approvals roster, architecture model, Packs, fleet). |

CURRENT-PLAN also records that "Yoke always installs git, so branches, worktrees, and merges are always available." That is a *desired* floor, not current F0 behavior: worktree create refuses a non-git directory today. The sweep keeps F0 as a column because the operator named it.

## Cell legend

- **P** proceeds — obligation met or honestly N/A at this rung.
- **D** degrades — named skip/fallback with a reason; work continues.
- **R** refuses — named reason; operator can act.
- **L** silently lies — success/green/done while the obligation did not happen.
- **n/a** the obligation does not exist at this rung under the intended ladder.

Intended rung is written as `want: Fk` using principle 3.

---

# A. Workflow definitions (live pins)

Four built-in workflows. All `source=built_in`, `status=active`, definition schema v4. Current canon generation is 6. There is **no** floor `task` workflow (principle 5).

Pinned-item concentration (from `workflows.definition.get`): issue v1 pins 1707 items, epic v1 pins 173 — **all terminal** (verified 2026-08-31: 1,588 done + 119 cancelled on issue v1; a live-item sweep shows 100% of open work on current canon — dash v6, issue v5). Old pins are inert history, immutability working as designed; ladder-as-data reaches every live item the day it ships. See the corrected gap 21.

## A1. `issue` current v5 (`workflow_version_id` 562)

| Axis | Value |
|---|---|
| Entry surfaces | `harness_skill`, `promotion` (no `web_form`, no `cli`) |
| Skill bindings | idea→refined-idea: `refine`; refined-idea→reviewed-implementation: `advance`; reviewed-implementation→implemented: `polish`; implemented→done: `usher` |
| Policies | `file_budget=required`, `path_claims=required`, `worktrees=single_implementation_lane`, `generated_children=none`, `qa=project_transition_defaults`, `approvals=definition_transitions`, `delivery=release_stage`, `ownership=single_item_claim` |
| Stages | idea → refining-idea → refined-idea → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done |
| Target-stage gates | refining-idea: `db_claim_prose` + `db_mutation/joint`; refined-idea: `db_claim_prose` + `architecture_impact`; implementing: `check_hard_blocks` + `claim_activation` + `architecture_impact`; reviewing-implementation: `db_claim_prose` + `db_mutation/evidence` + `architecture_impact`; reviewed-implementation: `architecture_impact` + `path_claim_boundary` + `qa_verification`; polishing-implementation: `architecture_impact`; implemented: `db_claim_prose` + `db_mutation/polish` + `architecture_impact` + `path_claim_boundary` + `qa_verification`; release: `architecture_impact` + `path_claim_boundary` + `qa_verification`; done: `architecture_impact` + `qa_verification` |
| Delivery default (yoke) | `yoke-internal` (merged → complete; no deploy stages) |
| Testing default (yoke) | Quick command plan 38 at `reviewing-implementation` |

### Ladder vs intended

| Cell | F0 | F1 | F2 | F3 | F4 | F5 | want |
|---|---|---|---|---|---|---|---|
| File Budget required | R if no files to size; readiness wants `## File Budget` in spec (DB-only P) | P (text) / R if unresolved modules | P | P | P | P | F0: agent-attested budget or off |
| Path claims required | R at required-gate; **L** at boundary (fail-open, no worktree) | P coverage / **L** boundary if no origin ref | P | P | P | P | F1: local integration ref; F2: origin |
| Worktree lane | **R** `worktree_create` "Not in a git repository" | P | P | P | P | P | F0: no-lane floor workflow |
| QA `project_transition_defaults` | **L** vacuous if no rows; **L** if QA tables absent | **L** vacuous unless plan attached | D to local `command` | P `command-ci` | P | P | F0–F1: no-tests attestation or skip; F3: CI |
| Approvals `definition_transitions` | R `GATE_APPROVAL_UNCONFIGURED` if gate listed and roster empty | same | same | same | same | P when roster exists | F5: roster; lower rungs: gate absent |
| Delivery `release_stage` | **L** empty `deployment_flow` skips evidence (`done_transition_deploy_gates.py:89-90`) | same | same | same | R if flow registered without evidence | P | F4: hosted flow; F1: merge-only satisfier stamped on item |
| Done nonce (usher) | R missing nonce when `delivery=release_stage` (`service_client_shared_done_ceremony.py:64-66`) | R | R | R | P via usher | P | want: nonce only at F4+; F1 merge-item close-out |
| `check_hard_blocks` / `claim_activation` on implementing | **L** status composer returns `None` (`backlog_authoritative_status_gate.py:223-224`) — named in definition, not run | **L** | **L** | **L** | **L** | **L** | want: live activation ops or remove from definition |

## A2. `epic` current v5 (`workflow_version_id` 563)

Same late-stage gate spine as issue, plus planning stages and `plan_simulation` into `planned`. Policies: `file_budget=required_per_task`, `path_claims=required_per_task`, `generated_children=epic_tasks`, `worktrees=worker_and_integration_lanes`, `qa=project_and_task_attachments`, `ownership=item_claim_and_task_lanes`, `delivery=release_stage`. Skill: refine → shepherd → refine → conduct → polish → usher.

| Extra vs issue | F0–F1 | F2–F5 | want |
|---|---|---|---|
| Parallel worktree lanes | R (git required, twice) | P | F0: no epic, or single-folder tasks |
| `plan_simulation` | R `GATE_PLAN_SIM_UNAVAILABLE` if helpers missing (loud) | P | keep loud |
| Task-scoped budget/claims | P defer until tasks exist (`file_budget_required_gate.py:88-96`) | P | honest defer is P |

## A3. `dash` current v6 (`workflow_version_id` 565)

Short path: idea → implementing → reviewing-implementation → done. Skill: `dash` through done. Policies: `file_budget=optional`, `path_claims=optional`, `path_survey=required`, `worktrees=single_implementation_lane`, `qa=optional_item_attachment`, `approvals=none`, `delivery=after_merge_action`, `ownership=exclusive_session_work_claim`. Entry: `web_form`, `cli`, `harness_skill`, `promotion`.

Implementing gates: `work_claim_activation`, `conflict_survey`, `architecture_impact`. Reviewing-implementation: `db_claim_prose`, `db_mutation/evidence`, `architecture_impact`. Done: `architecture_impact`, `qa_verification`, `dash_evidence`.

| Cell | F0 | F1 | F2 | F3 | F4 | F5 | want |
|---|---|---|---|---|---|---|---|
| `path_survey=required` vs `conflict_survey` stage gate | R missing survey | P (`--no-changes` allowed) | P | P | P | P | keep required for dash; see A3-gap |
| `path_survey` policy flag | **L**: `requires_path_survey` has **zero runtime consumers** other than the type; publishing `optional` does not remove `conflict_survey` from the stage | **L** | **L** | **L** | **L** | **L** | policy must move the stage gate |
| Worktree still required | **R** | P | P | P | P | P | F0: principle-5 task workflow, not dash-with-lane |
| `qa=optional_item_attachment` | **L** on yoke: testing default still attaches Quick command (plan 38) at reviewing-implementation; done still lists `qa_verification`; terminal settlement `require_any=True` when that gate is on the stage (`qa_terminal_settlement.py:220-224`, `:317`) | **L**/R | R without a case | P CI | P | P | optional means no default plan and no terminal require_any |
| `dash_evidence` | R missing evidence; requires `commit_sha` **and** `merge_sha` even when `no_changes=true` (`dash_execution.py:278-283`) | R until merge ceremony | P | P | P | P | F0: evidence without git SHAs; F1: local merge SHA |
| `delivery=after_merge_action` | Done nonce **not** required (mutations apply nonce only for `release_stage`) | P local merge | P | P | D after-merge deploy if posture on | P | intended |
| `approvals=none` | P (no gate) unless item posture `approval_on_done` | P | P | P | P | P | intended; posture is the offer-at-need |

## A4. `blitz` current v6 (`workflow_version_id` 564)

idea → refining-idea → refined-idea → implementing → reviewing-implementation → done. Skill: refine then `blitz`. Policies: `file_budget=optional`, `path_claims=optional`, `path_survey=required`, `worktrees=worker_lanes_optional_integration`, `qa=item_attachments`, `approvals=optional_named_gate`, `delivery=continuous_slice_actions`, `ownership=session_item_and_document_claim`. Implementing: `doc_claim_activation` + `conflict_survey` + `architecture_impact`. Done: `architecture_impact` + `qa_verification` + `doc_completion`.

| Cell | F0 | F1 | F2–F5 | want |
|---|---|---|---|---|
| Doc claim | P (DB) | P | P | keep |
| `doc_completion` | P/R on document sections, not git | same | same | keep |
| Continuous slice delivery | **L** if no flow; slices can merge/deploy when present | P merge | P | stamp rung |
| Worktree optional-integration | R without git | P | P | F0: no blitz, use task workflow |

## A5. Historical pins (not current, still live)

| Workflow | Version | Pins (known) | Implication |
|---|---|---|---|
| issue | 1 | 1707 | Pre-canon-6 ceremony; no ladder. Design that only ships in current canon does not reach most items until migrate. |
| issue | 3 | 7 | Intermediate |
| issue | 5 | 38 | Current |
| epic | 1 | 173 | Same pin-lag |
| epic | 5 | 2 | Current |
| dash/blitz | 1–5 | (prior canons) | Direct workflows also accumulated pins; current is 6 |

**Gap (hard wall / data):** workflow versioning is immutable (correct) but there is no capability-driven satisfier *inside* a pin. Shape differences are supposed to be data on one definition; instead they are frozen full-stack definitions plus a pile of v1 items.

---

# B. Engine gates and ceremonies

Catalog: `workflow_gate_catalog.py` (15 ids). Composer: `backlog_authoritative_status_gate.py`.

## B1. Status-gate composer

Enforcement: `backlog_authoritative_status_gate.py:47-155` dispatch `:158-232`.

- Unknown registered gate → **R** `GATE_IMPLEMENTATION_UNAVAILABLE` (`:225-231`).
- **Exception:** `check_hard_blocks` and `claim_activation` are explicitly **no-op** (`:223-224` return `None`) even though they are on issue/epic implementing stages. Catalog marks them `source_kind=activation_operation` — they are supposed to run at worktree activation, not status write. Status write still lists them, so a reader of the definition believes they gated the transition. **L** at every rung.
- `qa_bypass`/`force` strips non-activation gates; activation + `conflict_survey` remain.
- `reviewed-implementation` aggregates failures; other targets short-circuit.

| F0–F5 | want |
|---|---|
| **L** for the two no-op ids at all rungs | Either implement as status gates or stop listing them on stages |

## B2. `qa_verification`

Enforcement: composer `:242-290` → `qa_gates.check_verification_gate` / `check_done_gate`.

| Behavior | Evidence | F0 | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Pass if `YOKE_QA_GATE_BYPASS=1` | `qa_gates.py:112-113`, `:218-219` | D (env lie if used in prod) | D | D | D | D | D |
| Pass if QA tables absent | `qa_gates.py:115-116`, `:220-221` | **L** | **L** | **L** | **L** | **L** | **L** |
| Composer swallows `no such column/table` | `backlog_authoritative_status_gate.py:275-280` | **L** | **L** | **L** | **L** | **L** | **L** |
| Mid-gate: zero unsatisfied blocking rows including **empty set** → pass | `qa_gates.py:123-150` then fall through to pass | **L** | **L** | **L** | P if plan attached | P | P |
| `check_verification_entry` (existence) fails on zero rows | `qa_gates.py:63-100` | R | R | R | R | R | R |
| Status composer calls **gate not entry** | `:266-273` | **L** (entry unused on status write) | **L** | **L** | **L** | **L** | **L** |
| Browser disk/freshness skipped without git root | `qa_gates.py:257-258` (`if repo_root:`) | **L** | P | P | P | P | P |
| Engine itself names vacuous pass as worse than failure | `qa_no_tests_review_seed.py:1-6` | seed only if `attests_no_tests` | same | same | n/a | n/a | n/a |

Intended: F0–F1 attested no-tests → implementation_review seed (already exists, not default). F3 CI. Unattested + no command + no plan must **R**, not pass. Tables missing must **R**, matching `qa_plan_gate.py:27-34` (plan gate already refuses missing tables — inconsistent).

## B3. Terminal QA settlement / verdict

`qa_terminal_settlement.py:295-327`, invoked from composer `:103-105` on every terminal stage.

- Unsettled runs → **R** `GATE_QA_TERMINAL_SETTLEMENT`.
- If stage lists `qa_verification`, `require_any=True` (`:317`) — empty set **R** at done. This is the loud half of B2, but only at terminal, and only when the gate is on the stage.
- Dash/issue/epic/blitz current defs all put `qa_verification` on `done` → terminal require_any fires even for dash `optional_item_attachment`.

| F0 | F1 | F2 | F3 | F4 | F5 | want |
|---|---|---|---|---|---|---|
| R (no SHA-bound case) | R unless merge SHA + case | R | P | P | P | F0: no QA gate on task workflow; dash optional = no require_any |

## B4. `db_claim_prose` / `db_mutation` (joint, evidence, polish)

Joint: `db_mutation_gate_idea.py` + strategy `db_mutation_gate_strategy.py:45-116`. `state=none` → P. Missing `migration_model` + declared profile → **R** (`db_mutation_gate_idea.py:167-174`). Missing checkout → **warning, not block** (`:81-82`). Minimal schema → pass (`backlog_db_mutation_gate_runner.py` fail-open).

Strategy matrix (hardcoded cells, project `breakage_policy` is data):

| breakage_policy | migration_strategy | Result |
|---|---|---|
| any | additive_only | allow |
| founder_cutover | hard_cutover | allow |
| founder_cutover | expand_contract | R unless justification |
| compatibility_required | hard_cutover | R unless justification |
| compatibility_required | expand_contract | allow |

Evidence: apply receipt **or** retire decision (two satisfiers — closest thing to a real ladder today). Polish: evidence + backup.

| F0–F3 | F4–F5 | want |
|---|---|---|
| P when `state=none` (honest) | P/R per matrix | keep; missing tables must R not pass |

## B5. `architecture_impact`

Status runner blocks only `uncertain` past refined-idea (`backlog_architecture_gate_runner.py:71-87`). Catalog text claims it honors `architecture_model` (`workflow_gate_catalog.py:76-80`) — **the runner does not load the model**. Missing column → treat as `none`.

| All rungs | want |
|---|---|
| P for `none`; R for `uncertain`; **L** vs catalog wording | Either consult the model or change the catalog sentence |

## B6. `path_claim_boundary`

Documented fail-open (`path_claims_gate_boundary.py:21-32`): no `path_claims` table; no worktree branch; integration target unresolvable. Real worktrees with a resolvable ref enforce.

| F0 | F1 | F2 | F3–F5 | want |
|---|---|---|---|---|
| **L** (no worktree → pass) | **L** if no origin/`main` ref (`path_claims_boundary_git.py` prefers `refs/remotes/origin/<target>`) | P | P | F0: skip because claims off; F1: local `heads/<target>` as first satisfier, not fail-open |

## B7. `plan_simulation`

Helpers missing → **R** `GATE_PLAN_SIM_UNAVAILABLE` (loud). Contrast with QA tables missing → pass.

## B8. Activation / survey

| Id | Enforcement | F0 | F1+ | want |
|---|---|---|---|---|
| `work_claim_activation` | `direct_workflow_activation_gate.py` | R without claim/worktree | P | F0: task workflow without this gate |
| `doc_claim_activation` | same family | P (DB) | P | keep |
| `conflict_survey` | `conflict_survey_gate.py` | R missing/invalid | P; overlaps advisory | keep; policy must control presence |
| `check_hard_blocks` / `claim_activation` | composer no-op | **L** | **L** | see B1 |

## B9. `approval`

`approval_status_gate.py`. Unconfigured roster → **R** `GATE_APPROVAL_UNCONFIGURED`. Unresolved → **R** `GATE_APPROVAL_REQUIRED`. Dash posture `approval_on_done` hardcodes owner role (`dash_posture_gate.py:25-38`).

| F0–F4 | F5 | want |
|---|---|---|
| R if gate listed without roster | P | Gate absent until roster exists (offer-at-need, principle 6) |

## B10. `dash_evidence` / `doc_completion`

Dash: `dash_evidence_gate.py` + `dash_execution.py:263-284`. Requires result, passing verification, **commit SHA, merge SHA**, and touched_files **or** `no_changes`.

Doc completion: strategy document sections (Blitz).

| F0 | F1 | F2+ | want |
|---|---|---|---|
| R (no git SHAs) | R until merge ceremony | P | F0: evidence blob without SHAs; F1: local merge SHA as stamped rung |

## B11. Done ceremony (beyond status gates)

Engine: `packages/yoke-core/src/yoke_core/engines/done_transition_*.py`.

| Sub-gate | Evidence | F0 | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Done nonce | `service_client_shared_done_ceremony.py:32-68`; mutations only when `delivery=release_stage` | R issue/epic; P dash | same | same | same | P usher | P |
| Repo root required | `done_transition_runner.py` / gates `:48-60` | **R** exit 2 | P | P | P | P | P |
| No lane / no branch → continue without merge | `done_transition_runner.py:245-251` | **L** vs "merged" | **L** | **L** | **L** | **L** | **L** |
| Empty branch (lane exists, 0 commits) | `done_transition_gates.py:139-195` | n/a | **R** exit 8 | R | R | R | R |
| Blocked-flag read failure | `done_transition_gates.py:219-232` skip | **L** | **L** | **L** | **L** | **L** | **L** |
| Deploy flow empty or `*-internal` | `done_transition_deploy_gates.py:89-90` | **L** vs `delivery=release_stage` | **L** | **L** | **L** | P internal is honest merge-only if stamped | P |
| Unregistered flow | same `:98-111` | R exit 7 | R | R | R | R | R |
| Deploy evidence when flow is real | preconditions + guard | n/a | n/a | n/a | n/a | R | P |
| Preconditions relay fail | `done_transition_preconditions.py:165-167` fail-closed | R | R | R | R | R | R |
| GitHub sync after done | `done_transition_github_sync.py` 8-degraded | n/a | n/a | D after status already done | D | D | D |
| Finalize advisory | `done_transition_finalize.py:33-55` | D | D | D | D | D | D |
| Push fail | finalize `:215-243` warn | n/a | P (no remote) | D | D | D | D |

Intended done ladder (principle 3 example): merged+pushed+CI-green → merged locally → agent-attested. **Today there is no stamped rung.** Empty flow looks like the local/attested rung but is not recorded on the item as a satisfier.

## B12. Merge boundaries

| Path | Enforcement | F0 | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Bare merge refuse | `merge_boundary_ceremony.py:25-47` `YOKE_MERGE_NONCE` | R | R | R | R | R | R (good — prevents L) |
| Route: queue vs standalone | `merge_queue_route_selection.py:118-213` | n/a | P standalone | P | P | P | Queue if capability; **probe fail-closed** `:144-151` (good) |
| Local merge no remote | `merge_github_authority.py:94-95` | R no git | **P** | P+push | P | P | P |
| PR merge | `merge_worktree_pr.py:183-258` | n/a | n/a | P; **no checks → substitute `items.test_results` or R** (was a silent pass; now loud) | P | P | P |
| Merge-queue land | `merge_queue_route.py` | n/a | n/a | n/a | n/a | n/a | P; **drift check fail-open** `merge_queue_drift_gate.py:67` (**L**/D) |
| Dash `merge item` | standalone merge + evidence | R | P `--no-changes` still wants SHAs | P | P | P | P |

## B13. QA method routing (command vs command-ci)

| Mechanism | Evidence | F0 | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Register-time ladder | `qa_command_scope_routing.py` / `qa_command_plan_registration.py:176-178` | n/a | local `command` | local | `command-ci` if reachable | e2e/smoke stay local unless mapped | PR-first if `merge_queue` |
| Execution never silent-downgrades CI→local | `qa_case_ci_run.py:9-10` | n/a | n/a | n/a | R if CI unreachable | R | R (good) |
| Boot converge `refuse_unreachable_ci=False` | binds local + named reason | n/a | D named | D | n/a | n/a | n/a |
| QA PR-first probe fail → **dispatch fallback** | `qa_case_ci_entry_run.py:52-58` | n/a | n/a | n/a | D (cost, still verifies) | D | D |
| Merge landing probe fail → **R** | `merge_queue_route_selection.py:144-151` | n/a | n/a | n/a | n/a | n/a | R |
| Empty diff CI | `qa_case_ci_empty_diff.py` pass-by-inapplicability | n/a | n/a | n/a | P with receipt | P | P |
| Deploy CI gate skip if no `ci_workflow_file` | `deploy_pipeline_gates.py:229-235` returns **True** + skip message | n/a | n/a | n/a | n/a | **D**/borderline **L** if hosting declared without CI | P when declared |

Asymmetry: merge-queue probe fail-closed (doctrine); QA PR-first probe degrades to dispatch (honest D, not L); deploy CI skip is D with a message.

## B14. Lifecycle readiness (refine, not status catalog)

`idea_readiness_check.py:202-235`. File Budget / path-claim parity / architecture / `rg` module resolution. No `rg` → some checks skip (`:107-108`). No workflow policy schema → parity skipped (`:194-195`). Symlink issues advisory.

| F0 | F1+ | want |
|---|---|---|
| Weak / skip | P/R | F0: skip file checks honestly; do not invent PASS |

## B15. Delivery policy as obligation

`policies.delivery` is validated (`workflow_definition_validation.py:94-100`) and used for run-membership readiness (`workflow_delivery_binding_validation.py:15-32`) and done-nonce applicability. It is **not** what the done deploy guard reads. The guard reads `items.deployment_flow`. Empty/internal → no evidence. **L** vs "this workflow's delivery policy is an obligation."

---

# C. Posture knobs

Independence rule (project doctrine): File Budget and path claims are separate axes. Effective policies come from `workflows.item.get` → `effective_policies`. Item may tighten `optional→required` only if the key is on `item_posture_allowlist`.

| Knob | Lives | Off means | F0 | F1 | F2 | F3 | F4 | F5 | want |
|---|---|---|---|---|---|---|---|---|---|
| `breakage_policy` | `projects.breakage_policy` | no off; default `founder_cutover` (also fallback if column missing — **D**/L) | n/a | n/a | n/a | n/a | P matrix | P | keep; missing column R |
| File Budget | workflow + item tighten | `optional` → required-gate PASS | P (off) / R (on, no files) | P | P | P | P | P | keep; lifecycle file-line gate is **permanent no-op** (`backlog_file_line_gate_runner.py`) — **L** vs 350-line "always on" |
| Path claims | workflow + item tighten | `optional` → required-gate PASS; boundary still fail-opens | **L** boundary | **L** without origin | P | P | P | P | F1 local ref |
| `path_survey` | workflow (direct only) | publishing optional **does not** drop `conflict_survey` | R | P | P | P | P | P | policy drives stage list |
| `generated_children` | workflow | `none` vs `epic_tasks` | P | P | P | P | P | P | keep |
| `worktrees` | workflow | **no `"none"`** in the closed enum (`workflow_definition_validation.py:71-77`) | **R** create | P | P | P | P | P | add none **or** floor task workflow |
| DB claim | item JSON | `state=none` honest P | P | P | P | P | P/R | P/R | keep |
| `architecture_impact` | item enum | `none` no-op | P | P | P | P | P | P | catalog vs runner |
| `qa` policy | workflow | four values; **none means "no default"** but testing defaults and done-stage gate override | **L** | **L** | R/P | P | P | P | policy must control stage gate + defaults |
| `verification` item posture | allowlist | off = no extra selected plan | P | P | P | P | P | P | keep (offer-at-need) |
| `attests_no_tests` | project verification posture | on → seed implementation_review | P (honest substitute) | P | P | n/a | n/a | n/a | should be the F0–F1 default offer |
| `approvals` / `approval_on_done` | workflow + dash posture | `none` + unset = no gate | P | P | P | P | P | R/P | keep |
| `deployment` item posture | item | off = dash done does not require a run | P | P | P | P | R if on without envs | P | keep |
| `delivery` | workflow enum, not off | always one of three | **L** (see B15) | **L** | **L** | **L** | D/P | P | bind to stamped rung |
| `item_posture_allowlist` | workflow | empty = no tighteners | P | P | P | P | P | P | keep |

### Capabilities gates actually consult

| Capability | Missing behavior | Doctrine fit |
|---|---|---|
| `ci_workflow_file` | QA stays local `command` (good ladder); **deploy CI gate skips PASS** | QA good; deploy skip is D |
| `merge_queue` | standalone merge; probe fail-closed | good |
| `github` / sync mode | create still succeeds if sync fails (`backlog_rendering.py:132-141`) — **L** | create success ≠ GitHub issue |
| `migration_model` | declared DB claim R | good |
| `architecture_model` | status gate ignores; doctor HCs use it | split brain |
| `aws-admin` / environments | deploy ops fail | good if loud |
| Verification posture | unattested empty QA is green | **L** |

Yoke-project mechanics (this universe, not universal engine): delivery default `yoke-internal` for every workflow; testing default Quick command on **every** workflow including dash/blitz at `reviewing-implementation`. That is a project-data choice that collapses dash "optional QA" on this install.

---

# D. Implicit policy in engine code

Hardcoded assumptions that are not capabilities or posture knobs. File:line evidence. Ranked silent-lies first.

## D1. Silent lies

1. **QA tables missing → pass** — `qa_gates.py:68-69,115-116,220-221`; composer `:275-280`. Plan gate refuses the same absence.
2. **Vacuous QA on empty requirement set (mid-lifecycle)** — `qa_gates.py:123-150`; composer never calls `check_verification_entry`. Named as worse than failure in `qa_no_tests_review_seed.py:1-6`, but seed is opt-in via attestation.
3. **`check_hard_blocks` / `claim_activation` listed, not run** — `backlog_authoritative_status_gate.py:223-224`.
4. **Path-claim boundary fail-open** — `path_claims_gate_boundary.py:21-32,118-120,170-171`.
5. **Done without merge when lane/branch missing** — `done_transition_runner.py:245-251`.
6. **`delivery` policy unused as evidence obligation; empty/`*-internal` flow skips** — `done_transition_deploy_gates.py:89-90`.
7. **Item create succeeds when GitHub sync fails** — `backlog_rendering.py:132-141`; `backlog_create_op.py:335-343`.
8. **Blocked-flag done gate degrades open on read failure** — `done_transition_gates.py:219-232`.
9. **Browser QA disk/freshness skipped outside git** — `qa_gates.py:257-272`.
10. **`path_survey` policy does not control the survey gate** — `requires_path_survey` only defined in `workflow_effective_policies.py:53-54`; `conflict_survey` is hardcoded onto dash/blitz implementing stages.
11. **Architecture catalog vs runner** — catalog claims model honor; runner only blocks `uncertain`.
12. **File-line lifecycle gate no-op** — `backlog_file_line_gate_runner.py` ("prod core has no checkout").
13. **Dash/issue QA "optional" vs project testing defaults + done-stage `qa_verification`** — policy optional, stage and defaults not.
14. **Implicit trunk `"main"`** — `project_keys.py` default; `worktree_create.py:138-140`; `qa_case_ci_entry_run.py:75`; conflict survey / merge queue. Wrong-base until a later loud failure.
15. **Merge-queue drift fail-open** — `merge_queue_drift_gate.py:67`.
16. **`architecture_impact` missing column → `none`** — `backlog_architecture_gate_runner.py:47-48`.

## D2. Hard walls (lower rungs cannot satisfy; no weaker satisfier)

1. **Worktree create requires git** — `worktree_create.py:106-130`. No `worktrees=none`. F0 cannot activate dash/issue/epic/blitz implementing.
2. **Done ceremony requires repo root** — F0 cannot finish issue/epic.
3. **`dash_evidence` requires commit+merge SHAs** even for `no_changes` — F0 cannot close a dash.
4. **Named remote `origin`** on boundary, publish, queue landing.
5. **`merge_queue` capability ⇒ GitHub PR train** — correct undeclare remedy, not taught as the rung.
6. **Non-empty registered `deployment_flow` with target tier** — hosted evidence or usher redirect.
7. **Empty-branch guard** when a lane exists with 0 commits — fights evidence-only / strategy-doc dashes unless `--no-changes` merge records identity without commits (needs close-out proof).
8. **Issue/epic entry surfaces omit `web_form`/`cli`** on current issue v5 — intake shape is harness-shaped, not folder-shaped.

## D3. Honest refuse / named degrade (ladder still missing)

- Merge nonce / done nonce (prevent L; too coarse — no stamped weaker rung).
- Merge-queue capability probe fail-closed.
- Done preconditions fail-closed on relay failure.
- CI execution never silent-downgrades to local.
- PR "no checks" now requires `test_results` or refuses (`merge_worktree_pr.py:183-258`).
- DB `state=none` opt-out.
- Path-claim / File Budget effective `optional` PASS (the *required* gates; boundary is the lie).
- QA register-time command vs command-ci ladder (this is the one place principle 3 already exists).
- No-tests attestation → implementation_review seed (principle 3 prototype, opt-in).

---

# Ranked gaps

Ranking: silent lies worst, hard walls second, honest refusals that could degrade third. "Could degrade" means a lower reality-ladder rung should have a named satisfier instead of a wall.

## Silent lies (1–16)

1. **Vacuous QA green** — empty requirements pass mid-lifecycle; missing QA tables pass; composer skips schema errors. Engine comments already call this worse than failure. **Want:** missing tables R; empty unattested set R; attested no-tests seed as the F0–F1 satisfier; stamp the rung on the item.
2. **Named gates that do not run** — `check_hard_blocks`, `claim_activation` no-op on status write while listed on implementing. **Want:** live implementation or drop from stage lists.
3. **Path-claim boundary fail-open** — no worktree / unresolved origin → pass. **Want:** F1 uses local ref; F0 does not list the gate.
4. **Done without merge** when lane/branch absent, while still reaching `done`. **Want:** stamped rung (`agent-attested` / `merged-locally` / `merged+ci`) or R.
5. **`policies.delivery` is not the evidence obligation** — empty/`*-internal` `deployment_flow` skips deploy evidence. **Want:** delivery policy + capability registry pick a rung; item records it.
6. **Create success ≠ GitHub issue** when sync fails or is skipped. **Want:** F1 proceeds with `github_issue` null as a stamped "no-mirror" rung, not a swallowed error; F2 R or retry.
7. **`path_survey` policy is decorative** — stage still requires `conflict_survey`. **Want:** policy composes the stage list.
8. **QA policy `optional_*` vs done-stage `qa_verification` + project testing defaults.** **Want:** optional means the gate is absent and no default plan attaches.
9. **Architecture catalog vs runner** (model not consulted). **Want:** one story.
10. **Browser QA skipped without git root.** **Want:** R if browser methods exist; else n/a.
11. **Blocked-flag / finalize degrade-open** after or instead of refusal.
12. **File-line status gate no-op** while 350-line rule is taught as universal.
13. **Implicit `main`.** **Want:** derived `default_branch` or R "trunk unspecified."
14. **Merge-queue drift fail-open.** **Want:** R or named skip stamped on the batch.
15. **GitHub Step 8 after status already done** — degraded marker, item already terminal.
16. **`YOKE_QA_GATE_BYPASS` pass** — exists for tests; prod use is a lie.

## Hard walls (17–24)

17. **No floor `task` workflow** (principle 5). Every current workflow eventually wants a git lane, merge SHAs, or QA rows. F0 and non-code work have nowhere to go.
18. **`worktrees` enum has no `none`.** Combined with 17, F0 cannot activate.
19. **Dash evidence requires git SHAs** even for `no_changes`. Strategy-doc-only / folder work cannot close a dash honestly without a merge ceremony.
20. **Issue/epic `delivery=release_stage` + usher nonce** with no merge-only stamped satisfier. F1 should done on local merge; today usher+nonce or internal-flow skip (unrecorded).
21. ~~Most live items pinned to issue v1 / epic v1.~~ **Corrected (operator +
    verified 2026-08-31): NON-GAP.** Every issue-v1 pin (1,588 done + 119
    cancelled) and epic-v1 pin is terminal; a live-item sweep shows 100% of
    open work on current canon (dash v6, issue v5). Old pins are inert
    history — immutability working as designed — and ladder-as-data reaches
    all live work the day it ships. No migrate needed.
22. **Worktree / publish / boundary assume `origin`.** F1 should use local refs.
23. **Hosted `deployment_flow` has no "undeclared" teaching at the gate** — empty field silently drops evidence (that's a lie); a declared-but-unreachable flow is a wall. Principle 2 wants loud block or deliberate undeclare.
24. **Issue current entry surfaces omit form/cli** — folder-first intake is harness-shaped.

## Honest refusals that could degrade (25–30)

25. **Done nonce / merge nonce** — correctly prevent L, but they are binary. Want a ladder of ceremonies, not one nonce for every shape.
26. **`merge_queue` / `command-ci` once declared** — probe fail-closed is correct (principle 2); undeclare is the remedy and is not offered as a rung at the refusal.
27. **Empty-branch refuse (exit 8)** — correct for code lanes; wrong for evidence-only unless `--no-changes` is a first-class stamped rung.
28. **Approval unconfigured** — loud; should be "gate not present until roster exists" (principle 6) rather than a listed gate that refuses.
29. **Plan-simulation unavailable** — loud (good); keep.
30. **Joint DB gate without `migration_model`** — loud (good); F0–F3 stay on `state=none`.

---

# Design-session use

Do not file fixes from this document. For each ranked gap, the session chooses: (a) add a satisfier rung and stamp it on the item, (b) stop listing the gate on definitions that cannot satisfy it, (c) make the fail-open path a named refusal, or (d) accept as intentional and change the catalog/teaching so it is no longer a lie.

Prototype already in tree to steal from, not to bless as complete:

- QA register-time command vs `command-ci` ladder.
- No-tests attestation → `implementation_review` seed.
- PR no-checks → `test_results` substitute or refuse.
- Merge-queue capability probe fail-closed.
- DB mutation evidence **or** retire-decision (two satisfiers).

Missing primitive the rest of the session keeps circling: **the item-stamped rung** (principle 3, last clause). Nothing in `items` today records "this done was merged-locally" vs "merged+CI" vs "agent-attested." Until that column/event exists, every degrade is either a silent lie or an unrecorded skip.

## Evidence index (primary files)

- `packages/yoke-core/src/yoke_core/domain/workflow_gate_catalog.py`
- `packages/yoke-core/src/yoke_core/domain/backlog_authoritative_status_gate.py`
- `packages/yoke-core/src/yoke_core/domain/qa_gates.py`
- `packages/yoke-core/src/yoke_core/domain/qa_no_tests_review_seed.py`
- `packages/yoke-core/src/yoke_core/domain/qa_terminal_settlement.py`
- `packages/yoke-core/src/yoke_core/domain/path_claims_gate_boundary.py`
- `packages/yoke-core/src/yoke_core/domain/db_mutation_gate_strategy.py`
- `packages/yoke-core/src/yoke_core/domain/db_mutation_gate_idea.py`
- `packages/yoke-core/src/yoke_core/domain/workflow_definition_validation.py`
- `packages/yoke-core/src/yoke_core/domain/workflow_effective_policies.py`
- `packages/yoke-core/src/yoke_core/domain/dash_execution.py`
- `packages/yoke-core/src/yoke_core/domain/dash_evidence_gate.py`
- `packages/yoke-core/src/yoke_core/engines/done_transition_runner.py`
- `packages/yoke-core/src/yoke_core/engines/done_transition_gates.py`
- `packages/yoke-core/src/yoke_core/engines/done_transition_deploy_gates.py`
- `packages/yoke-core/src/yoke_core/domain/merge_queue_route_selection.py`
- `packages/yoke-core/src/yoke_core/domain/merge_worktree_pr.py`
- `packages/yoke-core/src/yoke_core/domain/deploy_pipeline_gates.py`
- `packages/yoke-core/src/yoke_core/domain/builtin_direct_workflow_definitions.py`
- `packages/yoke-core/src/yoke_core/domain/builtin_delivery_workflow_definitions.py`

Live DB: `workflows.definition.get`, `workflows.version.list`, `workflows.mechanics.get` (yoke delivery default `yoke-internal`; testing default plan 38 Quick command on all four workflows at `reviewing-implementation`).
