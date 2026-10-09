# Onboard Step 1: Strategy Conversation

Entry: wire-up verified and run active. Skip only when all five docs are accepted,
non-placeholder content. Rows: `repo-survey`, `strategy-setup`.

Strategy owns every later profile/Pack/environment/work proposal.
DB strategy documents are authority; `.yoke/strategy/` is a gitignored render.
Read the selected write's `--help`; contract:
[project configuration](../../../../.yoke/docs/reference/db-reference/functions-project-configuration.md).

## Top up, then read

Run the top-up every time: it seeds missing placeholders without changing
existing rows. Record each list row's `updated_at` for CAS. Read all five
documents with plain calls, not a shell loop; the list is metadata only.

```bash
yoke strategy seed-defaults --project {project} --json
yoke strategy doc list --project {project} --json
yoke strategy doc get MISSION --project {project}
yoke strategy doc get VISION --project {project}
yoke strategy doc get MASTER-PLAN --project {project}
yoke strategy doc get LANDSCAPE --project {project}
yoke strategy doc get CURRENT-PLAN --project {project}
```

Classify seeded template text as placeholder and operator content as accepted.
If all are accepted, report and skip drafting.

## Ground drafts in the repository

Use `rg --files {checkout}` plus focused manifests, README/runbooks,
package/build/test/runtime/service entrypoints, deploy configuration and
`.yoke/` contracts in either repo mode. Name external systems, secrets,
targets, unknowns and existing docs feeding strategy/profile.

Classify every `.github/workflows/` file: runs the tests, builds artifacts,
deploys, releases, or other. Record `Jenkinsfile`, `.gitlab-ci.yml`,
`bitbucket-pipelines.yml` and `fastlane/Fastfile` separately.
Only the actual Actions test workflow can be `ci_workflow_file`; declaring
a deploy/release workflow gives unrelated proof and registration refuses.
Non-Actions CI keeps the local `command` runner.

```bash
yoke onboard checklist --run-id {run_id} --row-status repo-survey=verified --evidence repo-survey="{manifests/docs/build/test/runtime/external facts; each workflow=purpose; other CI or none}"
```

Propose complete drafts from conversation and survey; ask only unresolved
purpose/audience/priorities. Refine until accepted:
MISSION = reason; VISION = desired state and deliberate exclusions;
MASTER-PLAN = route; LANDSCAPE = competitive/technical terrain;
CURRENT-PLAN = concrete orderable near-term outcomes for step 8.
Existing reality is the floor, not a blank slate.

## Write accepted changes under the strategy claim

Acquire the explicit project's STRATEGIZE process claim before
`strategy.doc.replace`; checkout mapping may not yet exist.
`claim_conflict` means STRATEGIZE/FEED owns the write window: mark
`strategy-setup=blocked`, name holder recovery, and stop without silently waiting.

```bash
yoke claims work acquire --process STRATEGIZE --project {project}
```

Write each accepted draft to a scratch file and CAS against the recorded token.
Accepted-as-is docs stay untouched. If CURRENT-PLAN exceptionally remains absent
on an older control plane after top-up, use create instead of replace.

```bash
yoke strategy doc replace {SLUG} --project {project} --base-updated-at {updated_at} --content-file {draft_path}
yoke strategy doc create CURRENT-PLAN --summary "Near-term executable work." --state "draft" --project {project} --content-file {draft_path}
```

Release the process claim on **every exit**, including failure; obtain its ID
from the registered holder-list if needed. Preserve completed CAS writes;
block with exact failure/recovery and retry only remaining slugs.

```bash
yoke claims work release --claim-id {claim_id} --reason "onboard strategy writes complete"
yoke strategy render --project {project} --target-root {checkout}
yoke onboard checklist --run-id {run_id} --row-status strategy-setup=configured --evidence strategy-setup="{written slugs} written; {accepted slugs} kept; local render refreshed"
```

Next: [profile-and-scaffold.md](profile-and-scaffold.md).
