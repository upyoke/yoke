# Deployment runs and packaged capabilities

The rules file every session loads carries the short normative form of each rule. This document is the deep home the rules file points at: the same rules with the reasoning, the worked failure modes, the flag matrices, and the edge cases that decide close calls. Read the section you need before the action it governs — nothing here is optional background, it is simply longer than a startup channel can carry.

## Deployment runs

- **One deploy lock per project; flow id != run id.** Creating a run and executing one both refuse unless the calling session holds the project's `DEPLOY:<project-slug>` coordination claim, so one driver owns a release pair end to end: `yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason R` before the pair, the matching `... release` after, and the human-only `yoke coordination-claim release` for a hold stranded by a dead driver (nothing reclaims it — the pipeline outlives its local driver). A hosted flow definition id is not a run id; run ids look like `run-YYYYMMDD-NNN`, and `/yoke usher PREFIX-N` creates runs through `yoke deployment-runs start-for-item`, writes `deployment_run_items`, executes the pipeline, then moves members to `done`.
- **Disable definitions; retain history.** `yoke deployment-flows set-status <flow-id> disabled` prevents new assignments and runs without deleting the definition or any historical run. A definition referenced by a run is immutable and cannot be deleted.
- **Schema/env shape:** `deployment_runs` has no `item_id`; `deployment_run_items` may be empty for started environment runs. The HTTPS product/API environment is the normal relayed authority, and it drives ordinary delivery end to end — create, start-for-item, execute, watch, retry, close-out — over whichever connection holds the run row. A local-Postgres `*-db-admin` environment is direct database write authority for sanctioned source-dev/admin work and audited break-glass SQL; a deployment needs it only when the run replaces that control plane's own serving API, and the executor refuses that one case by name and says which connection to use. Never go looking for control-plane database credentials to deploy a project: they are not the project's application database credentials, and a project whose control plane someone else operates has none to obtain.

## Binding-based multi-project delivery

A `github-actions-workflow` stage may declare `input_bindings`, naming another
registered project's branch: `{"consumer_sha": {"project": "other", "branch":
"main"}}`. The build that stage dispatches ships that project's code alongside
the run's own candidate, so the run delivers two projects, not one.

- **The branch resolves once, at start.** The run records the exact commit it
  resolved for each bound project in `deployment_runs.bound_sources`, beside
  its own `release_lineage`. Every later reader — the stage that substitutes
  the placeholder, enrollment, composition validation, run detail, the
  Frontier delivery box — reads that record. Nothing re-resolves a branch
  afterwards, so a retry cannot ship a commit the first attempt did not. Read
  it with `yoke deployment-runs get RUN-ID bound_sources`, and read what a
  flow binds with `yoke deployment-flows stages FLOW-ID`.
- **A release attributes the commits it wrote itself.** A promotion that
  rewrites a version pin pushes a commit no backlog item authored, into the
  range the next release reads. The producing run records it — `yoke
  deployment-runs release-output record RUN-ID --project P`, stored as
  `outputs` on that project's `bound_sources` entry — and carried-work
  attribution reads that record only for a commit no item claimed, so the
  item always wins and unexplained real code still refuses. Omit `--commit`
  and the branch the run itself bound names the commit. Recording is refused
  by name for a commit an item already owns, one the run merely pinned, and
  one that does not descend from that pinned source.
- **The record waits for its own column; the release does not.** The column
  is additive, so it arrives on the boot converge of a build carrying it —
  and that build is deployed by a run this same code drives, against the
  database as it stands before that converge. During that one window the
  branch still resolves and the bound stage still dispatches the resolved
  commit; only the durable record waits. Delivery credit for bound-project
  items begins with the first run started after the converge.
- **A branch that cannot be reached refuses the start by name.** It is
  resolved from the bound project's registered checkout, or through that
  project's own authorized repository binding when this host holds no
  checkout; neither answering names both repairs rather than dispatching an
  unrecorded binding.
- **Membership follows the source.** Start-time enrollment runs once per
  project the run ships — its own plus every bound one — against that
  project's recorded commit, so a bound project's delivery-ready items become
  ordinary members. They get a membership row, a requirement snapshot, and the
  item-scoped QA wake, exactly like own-project members. An item whose project
  the run ships no source for is still refused.
- **Delivery is judged per project.** An item counts as delivered by a
  succeeded run whose recorded commit *for that item's project* contains its
  merge. That is why a bound-project item needs no second run on its own flow
  to record a delivery the carrying run already made — and why a run that
  carried nothing for a project delivers nothing for it, however recent.
- **One commit per project per run.** Two bindings naming the same project
  with different branches are refused: delivery could not then say which
  commit the release shipped for that project.

## Release-time roles

A run that carries members is acted on by two different sessions, and neither
learns the other's part from its own skill. The split is the whole rule:

- **The seat driving delivery owns the run.** It holds `DEPLOY:<project>` for
  the whole pair, pins one source SHA, creates the stage and production runs
  from that SHA, and starts each one with `yoke --env CONTROL-PLANE watch
  deploy -- RUN-ID`. The start enrolls every delivery-ready item its candidate
  carries that no live or succeeded release already holds — whether the work
  landed since the last release or long before it — and applies the composition
  check itself, so membership needs no separate step:
  `yoke deployment-runs add-item RUN-ID PREFIX-N` is for the other case, an
  item whose code the candidate does not carry but which the run should still
  deliver, and `validate-composition` composes the run now and reports what
  it enrolled or why it refused. An item a cancelled run left behind therefore needs
  no attaching, and `yoke steering report get` names any landed item no
  release holds so nobody has to notice one going stale. The driving seat does not run a member's item QA and
  does not close a member out.
- **The attach says what the run can do for the member.** Two independent
  capabilities: a run **checks** a member only through an item-scoped QA
  stage, and **closes** one only as that item's completion flow or as another
  project's run carrying this project's source. Most delivery flows check
  nothing and close everything they carry, so a missing item-scoped stage is
  no reason to refuse an attach — but a run that can do neither gives the
  member nothing, and membership still holds the landing, so the next start on
  the item's completion flow will not enroll it. `add-item` names that case
  with the flow that can close the item; `validate-composition` names any
  member already in it.
- **The member owner owns its own item.** Its merge parked it at the flow's
  release wait holding its work claim; the deployment wake re-enters it for its
  QA stage, when its own item-scoped QA is accepted, and again when delivery
  clears. A wait wake is withdrawn — the existing message-cancel path —
  when its run reaches a terminal status or its member is no longer
  outstanding (the item-scoped stage is credited, or the item is done), so
  a late delivery cannot instruct settled work. Recorded delivery attempts
  stay as evidence. A wake whose every attempt in a bounded window met the
  same non-transient condition (a native turn that never exited) escalates
  on the receipt and names that condition, rather than retrying in silence.

**A QA stage credits only requirements bound to its own stage name** — an
item-scoped stage only ones bound to the member too. So the member owner runs
`yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N`, and
the unscoped run-wide form is refused rather than recording a pass the stage
ignores. `yoke qa case run --requirement-id N` credits that requirement's
existing binding and never a stage, so it cannot substitute either: when the
requirement is already bound to an item-scoped stage it refuses and names
the plan-run invocation that would credit it. Dropping `--stage` or
`--member` is the failure that looks like success: every case passes and the
stage still reads unsatisfied.

**`yoke merge item` is the one agent-facing close-out**, at the merge and again
at the release wait, carrying `--result` and `--verification` both times. There
is no internal done engine to substitute: `done-transition --skip-deploy`
records a selected-flow delivery as out-of-band, which is a false record and is
refused once that flow has a succeeded run covering the merge. It remains only
for a flow that genuinely delivers nothing.

Each of those commands carries the full matrix in its own `--help` — that is
the deep home for this section, and it is the one that cannot go stale against
the code: `yoke qa plan run --help` (subject/scope matrix), `yoke qa case run
--help` (which credit it cannot earn), `yoke merge item --help` (close-out
routes and the queue landing handoff), and `yoke deployment-runs --help` (the
item-bound batch release, plus the itemless environment release).

## Pack-first capabilities

- **If your project distributes reusable capabilities, package them as Packs.** Reusable ops workflows, deployment tooling, and infrastructure patterns live in a focused `packs/<slug>/` bundle with immutable versions, explicit files, settings, dependencies, documentation, and verification.
- **Installed Pack files belong to the project.** They land in the target project repo and may be customized there. Yoke records the installed baseline in `.yoke/packs.json` only so that project owners can preview and apply one Pack update with a three-way merge; it does not police drift, prune files, or synchronize the whole project.
- **Improve the Pack when the general capability evolves.** Publish a new Pack version, then let each project choose whether and when to update it. Project-only behavior remains project-owned and need not flow back into the Pack.
- **Project config lives in DB settings/capabilities or project-local `.yoke/` policy docs.** Use `project_capabilities`, `sites.settings`, and `environments.settings` for credentials and runtime config. Pack install settings only specialize generic source for the target project; runtime-generated files land in scratch/deploy-run output or the target project repo.
- **Provider credentials are capability-owned, not ambient shell.** For AWS, the source of truth is the project `aws-admin` capability: non-secret settings in `project_capabilities`, while secret material lives in machine-local capability secret files under `~/.yoke/secrets/capability-secrets/<project>/aws-admin/`. The `capability_secrets` table is not the storage shape for `aws-admin` secrets. A naked `aws ...` command may fail even when the project is correctly configured because the credentials are not exported into the shell. Use Yoke-owned capability resolver surfaces to materialize credentials into a subprocess env without printing secret values; when a resolver has not yet been wrapped, treat it as a source-dev/admin helper rather than an agent recipe. Verify by listing keys/settings or redacted evidence; never log raw secret values.
