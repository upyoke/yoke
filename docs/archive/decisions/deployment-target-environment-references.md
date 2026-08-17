# Deployment targets are environment references, not labels

Deployment flows and runs once carried a free-text `target_env` label.
The environment registry arrived later with its own short display names,
so `"production"` on a flow and `"prod"` on the environment row named the
same thing without ever joining. Every consumer compensated separately:
QA execution targeting and the fleet-preflight receipt store each kept an
alias map, the deploy-env validator unioned flow labels with registry
names so both vocabularies counted as "valid", and the merged-gate branch
resolver compared the flow label against `environments.name` — a silent
miss for any project whose label and name diverged, which would have
ignored a declared `git.branch` the day one was set.

The replacement is a typed pair on both `deployment_flows` and
`deployment_runs`:

- `target_tier` — `persistent` (deploys to a registered environment),
  `ephemeral` (per-run preview substrate from unmerged branches), or
  `NULL` (merge-only flows with no deploy target);
- `target_environment_id` — a foreign key into `environments`, required
  exactly when the tier is `persistent` (a CHECK enforces the pairing).

Rules that keep the seam closed:

- Display surfaces render `environments.name`; nothing user-facing prints
  a raw id or tier when a name resolves.
- Runtime environment identity (`YOKE_ENVIRONMENT`) carries the
  environment name — the deploy pipeline sets it from the referenced row.
- Fleet-preflight receipts key on the environment name, and so does the
  desired-pin writer. A dispatched workflow therefore receives the
  environment name — flow stages ask for it with the
  `{target_environment}` input placeholder, which resolves from the run's
  typed reference. The one sanctioned translation left is the last step
  before a foreign train: Platform's promotion workflow takes its own
  `stage`/`production` input vocabulary that Yoke cannot rename, so the
  bridge derives that label where it dispatches and nowhere else. A label
  that travels further than its own dispatch is the defect this rule
  prevents: it reached the pin writer once, which refused the unregistered
  name and left desired authority a release behind.
- `items.deployed_to` stamps the environment name; `local` remains the
  non-registered local label.
- The valid-deploy-environment set comes from the registry alone — flow
  rows can no longer widen it, because their reference must already be a
  registry row.

The ordered migration that ended the label era resolves each legacy label
to the project's environment row — minting registry rows for label-era
projects that predate the registry — recodes stamped labels, receipt
events, release-pin map keys, and stored QA content, then drops the label
columns behind a serving floor.
