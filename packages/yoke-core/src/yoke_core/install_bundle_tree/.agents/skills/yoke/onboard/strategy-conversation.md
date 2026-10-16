# Onboard Step 1: Strategy Conversation

Entry: wire-up verified and run active. Skip only when existing work was
scanned, all five docs are accepted non-placeholder content and CURRENT-PLAN
names the first work. Rows: `repo-survey`, `strategy-setup`.

Strategy owns every later profile/Pack/environment/work proposal.
DB strategy documents are authority; `.yoke/strategy/` is a gitignored render.
Read the selected write's `--help`; contract:
[project configuration](../../../../.yoke/docs/functions/project-configuration.md).

## Confirm what to scan

Existing work is the starting point. Before drafting, tell the user what you
will read and ask what else belongs, in one message:

- open issues and pull requests on the project's forge;
- local session transcripts for this checkout, from every harness on this machine;
- what else to include: documents outside the repo, other machines with
  transcripts, trackers on other systems.

```bash
yoke github open-work list --project {project} --json
```

It reads through the project's GitHub binding; `truncated` means raise
`--limit` (max 200). A refusal names its recovery: with no GitHub binding, or
on another forge, ask the user for an export of open issues and PRs. Transcript
stores are harness facts: read `session_transcripts` from each
`.yoke/harness/<harness-dir>/manifest.json` (claude-code → claude) and keep
only files its `project_match` ties to this checkout. Read summaries and the
last turns of recent sessions for unfinished intent, not whole histories.
Another machine's transcripts are read by an agent on that machine or from
files the user copies over; never assume they are absent.

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

## Ground drafts in the repository

Use `rg --files {checkout}` plus focused manifests, README/runbooks,
package/build/test/runtime/service entrypoints, deploy configuration and
`.yoke/` contracts. Name external systems, secrets, targets and unknowns.

Classify every `.github/workflows/` file: runs the tests, builds artifacts,
deploys, releases, or other. Record `Jenkinsfile`, `.gitlab-ci.yml`,
`bitbucket-pipelines.yml` and `fastlane/Fastfile` separately.
Only the actual Actions test workflow can be `ci_workflow_file`; declaring
a deploy/release workflow gives unrelated proof and registration refuses.
Non-Actions CI keeps the local `command` runner.

```bash
yoke onboard checklist --run-id {run_id} --row-status repo-survey=verified --evidence repo-survey="{sources scanned with counts: issues, PRs, transcripts per harness, user additions}; {manifests/docs/build/test/runtime facts}; {each workflow=purpose; other CI or none}"
```

## Draft, then decide one thing at a time

Draft from the scan and the repository; ask only what neither answers.
MISSION = reason; VISION = desired state and deliberate exclusions;
MASTER-PLAN = route; LANDSCAPE = competitive/technical terrain;
CURRENT-PLAN = concrete orderable near-term outcomes, each naming the issues,
PRs and session threads it continues. A large thread that needs its own plan
gets one concise initiative doc that CURRENT-PLAN points to. Existing reality
is the floor: carry open work forward rather than restarting it.

Show the drafts, then walk the open decisions one at a time, most important
first, each with your recommendation. The last decision is the first work:
the CURRENT-PLAN outcome that steering files first. Existing checks,
approvals and project rules stay as they are unless the user changes them.

## Write accepted changes under the strategy claim

Acquire the explicit project's STRATEGIZE process claim before
`strategy.doc.replace`; checkout mapping may not yet exist.
`claim_conflict` means STRATEGIZE/FEED owns the write window: mark
`strategy-setup=blocked`, name holder recovery, and stop without silently waiting.

```bash
yoke claims work acquire --process STRATEGIZE --project {project}
```

Write each accepted draft to a scratch file and CAS against the recorded token.
Accepted-as-is docs stay untouched. Initiative docs and a CURRENT-PLAN still
absent on an older control plane use create:

```bash
yoke strategy doc replace {SLUG} --project {project} --base-updated-at {updated_at} --content-file {draft_path}
yoke strategy doc create {INITIATIVE-SLUG} --summary "{one line}" --state "draft" --project {project} --content-file {draft_path}
```

Release the process claim on **every exit**, including failure; obtain its ID
from the registered holder-list if needed. Preserve completed CAS writes;
block with exact failure/recovery and retry only remaining slugs.

```bash
yoke claims work release --claim-id {claim_id} --reason "onboard strategy writes complete"
yoke strategy render --project {project} --target-root {checkout}
yoke onboard checklist --run-id {run_id} --row-status strategy-setup=configured --evidence strategy-setup="{written slugs} written; {accepted slugs} kept; first work: {outcome}; local render refreshed"
```

Next: [profile-and-scaffold.md](profile-and-scaffold.md).
