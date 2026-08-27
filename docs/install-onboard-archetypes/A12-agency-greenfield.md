# A12 — Morgan, agency greenfield, macOS, no remote, AWS "later"

**Vector:** agency · idea-only · hosting none yet (AWS planned) · macOS ·
no remote · deploy none.

Morgan is starting a client greenfield in a new folder. The SOW says "AWS in
phase 2". They want Yoke now for specs, AWS later without lying to Usher.

## Fit / break / gaps

| | |
|---|---|
| Fits | Create-new, keep local, skip hosting, local universe. Confirm merge-only or no default until AWS is connected later. |
| Breaks | Persistent delivery is unavailable while hosting is deferred, so onboarding cannot create premature stage/prod flows. |
| Gaps | Re-running `/yoke onboard` must still replace the temporary delivery choice cleanly when AWS becomes verified. |

## Transcript — installer + wizard

Identical to A01 until hosting. **Skip for now** (explicit: "connect later via
`/yoke onboard` or re-run"). Apply. Hand-off.

## Transcript — `/yoke onboard` (first run)

Empty folder (wizard created git repo). Strategy for the client product.
Hosting is deferred, so the profile offers only merge-only or no default.
The agency confirms **merge-only** for local delivery until AWS is ready.

Step 5 creates no site or environment. It registers the empty-tier local-merge
flow, verifies the project default, marks domain setup not needed, and defers
the first infrastructure apply. Choosing no default would instead clear the
attachment and make seed-work omit `--deployment-flow`.

Later, when AWS arrives: re-run `/yoke onboard`. Step 4 connect:

```
yoke projects capability secret set --project {p} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability secret set --project {p} --cap-type aws-admin --key secret_access_key --value-stdin
yoke projects capability-settings set --project {p} --cap-type aws-admin --key region --value {region}
yoke aws exec --project {p} -- sts get-caller-identity --output json
```

Then step 7 `[y/N]` apply. Only **then** should a persistent default flow exist.

## Test setup

**Reality:** wizard-created empty git repo — **no tests**. Phase-2 AWS does
not change that.

**Bind today:** same as A01. `yoke qa plan create` needs an environment;
creating stage/prod only so a plan can exist is the G-qa-plan-needs-env
lie.

**Onboard:** no test question. CURRENT-PLAN will name client work items, not a
reusable QA plan, so seed will not attach one.

**Ask that should happen:** scaffold vs attested no-tests before any item
can hit reviewing-implementation. Recommend scaffold if they accepted
`webapp-scaffold`; else attest no-tests.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Future AWS | Hosting skip + profile "defer infra" | Do not create persistent flows while deferred | Merge-only or empty default until apply succeeded |
| Deploy on items | Idea uses `deploy-defaults get` | Empty-tier default → Route A with no run; empty default → omit flow | Replace with persistent only after hosting verifies |
| Migration | Still N/A | — | Add `migration_model` when a DB exists |

Ledger: G-test-setup-unasked, G-no-tests-posture, G-qa-plan-needs-env.
