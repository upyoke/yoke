# Onboard Step 1: Strategy Conversation

Strategy is the root: everything later — the execution profile, Packs, environments, the first work items — derives from and is justified by these docs. This step fills all five default strategy docs in one conversation: `MISSION`, `VISION`, `MASTER-PLAN`, `LANDSCAPE`, and `CURRENT-PLAN`.

- **Entry:** wire-up verified; checklist run active.
- **Skip:** all five docs present with accepted, non-placeholder content → report the corpus state and skip.
- **Rows:** `repo-survey`, `strategy-setup`.

The strategy authority is the DB `strategy_docs` table, scoped per project. `.yoke/strategy/` is only a gitignored local render. Reads go through `yoke strategy doc get`, writes through the compare-and-swap replace below.

## 1. Top Up The Default Corpus

Run the seed top-up first, every time. It seeds any missing default slug as a placeholder and never touches an existing row, so it is safe on every run and heals older projects whose corpus predates the current default roster:

```bash
yoke strategy seed-defaults --project {project} --json
```

The result names seeded vs already-present slugs. After this, every default slug has at least a placeholder row, so the writes below are always replaces against an existing row.

## 2. Read The Corpus

```bash
yoke strategy doc list --project {project} --json
yoke strategy doc get {SLUG} --project {project}
```

Record each row's `updated_at` from the list output — the replace write below needs it as the compare-and-swap base. Classify each doc as **placeholder** (still the seeded template text, no project-specific content) or **accepted** (operator-authored content). If all five are accepted, apply the skip: report and move to step 2 of this skill.

## 3. Repo Survey

Survey the project checkout in both modes — in a freshly created repo it is trivially quick; in an existing repo it grounds everything downstream. Prefer `rg --files {checkout}` and focused reads of manifests, README/runbooks, package files, CI definitions, deployment config, test config, and existing `.yoke/` contract docs. Identify:

- Project type, package manager, build/test commands, service entrypoints, and runtime versions.
- Existing docs that should feed the strategy drafts and the later execution profile.
- External systems, required secrets, deployment targets, and unknowns.
- **CI, one workflow at a time.** List every file under `.github/workflows/`
  and classify each by what it does: runs the tests, builds artifacts,
  deploys, releases, or something else. Record any non-Actions CI system the
  repo carries — a `Jenkinsfile`, `.gitlab-ci.yml`, `bitbucket-pipelines.yml`,
  or `fastlane/Fastfile`. Only the workflow that runs the tests can become
  the project's `ci_workflow_file` in step 5; a deploy or release workflow
  declared there makes the verification gate report a green that proves
  something else, and the registration refuses it by name. A project whose CI
  is Jenkins, GitLab, Bitbucket, or a store upload keeps the local `command`
  runner — that is a correct outcome, not a gap.

Do not guess what the survey can answer. Then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status repo-survey=verified \
  --evidence repo-survey="surveyed manifests, docs, CI, and runtime shape: {short facts}; workflows {name=purpose, ...}; other CI {systems or none}"
```

## 4. Draft And Refine All Five Docs

Propose complete drafts from the conversation so far plus the survey — a smart proposal, never a blank interrogation. Ask only for what neither the conversation nor the repo can answer (product purpose, who it serves, near-term priorities). Refine each draft in place with the operator until accepted:

- **MISSION** — the one-paragraph reason the project exists.
- **VISION** — the desired end state and what is deliberately out for now.
- **MASTER-PLAN** — the phased route from here to the vision.
- **LANDSCAPE** — the competitive/technical terrain the strategy responds to.
- **CURRENT-PLAN** — the near-term executable plan. Write it as concrete, orderable outcomes: step 8 of this skill derives the first backlog items directly from it.

In existing-repo mode, weave surveyed reality into the drafts (what the repo already does is the floor for MISSION/CURRENT-PLAN, not a blank slate).

## 5. Acquire The Strategy Write Window

`strategy.doc.replace` is authorized by the `STRATEGIZE` process work claim on the target project — the server bounces replace without it. Acquire it before writing, exactly as `/yoke strategize` does (operator/debug adapter shown; the function id family is `claims.work.acquire` with a process target):

```bash
yoke claims work acquire --process STRATEGIZE
```

If acquisition reports `claim_conflict`, another session is running `/yoke strategize` or `/yoke feed` for this project. Do not wait silently: record the block and stop this step.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status strategy-setup=blocked \
  --blocker strategy-setup="strategy write window held by another session (STRATEGIZE/FEED conflict group); finish or end that session, then re-run /yoke onboard --run-id {run_id}"
```

## 6. Write The Accepted Docs

For each accepted draft, write the content to a scratch file with the Write tool, then replace with the compare-and-swap base recorded in section 2:

```bash
yoke strategy doc replace {SLUG} --project {project} \
  --base-updated-at {updated_at} --content-file {draft_path}
```

Docs the operator explicitly accepts as-is (already non-placeholder) are left untouched. If `CURRENT-PLAN` unexpectedly has no row (a corpus older than the seed top-up on a control plane that has not run it), create it instead:

```bash
yoke strategy doc create CURRENT-PLAN --project {project} --content-file {draft_path}
```

After the writes, release the process claim (resolve the claim id from `yoke claims work holder-list` if needed):

```bash
yoke claims work release --claim-id {claim_id} --reason "onboard strategy writes complete"
```

Release on every exit from this step, including the failure floor — the claim is the only lock this step holds.

## 7. Render And Mark

Refresh the local rendered views so later steps and the operator read current content:

```bash
yoke strategy render --project {project} --target-root {checkout}
```

Echo the evidence (slugs written vs kept), then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status strategy-setup=configured \
  --evidence strategy-setup="strategy corpus filled: {written slugs} written, {kept slugs} kept"
```

**Failure floor:** on any failure, record `strategy-setup=blocked` with the blocker text and stop. Docs already replaced stay written — the compare-and-swap base makes a retry of the remaining slugs safe.

Continue to step 2 of this skill: read [profile-and-scaffold.md](profile-and-scaffold.md).
