# A12 — Morgan, agency greenfield, macOS, no remote, AWS "later"

**Vector:** agency · idea-only · hosting none yet (AWS planned) · macOS ·
no remote · deploy none.

Morgan is starting a client greenfield in a new folder. The SOW says "AWS in
phase 2". They want Yoke now for specs, AWS later without lying to Usher.

## Fit / break / gaps

| | |
|---|---|
| Fits | Create-new, keep local, skip hosting, local universe. Hosting "connect later via /yoke onboard or re-run". |
| Breaks | Confirming the stock execution profile **now** creates stage/prod/flows before AWS exists. Idea then assigns that flow. |
| Gaps | Deferred hosting must **forbid** persistent deploy defaults. Re-run `/yoke onboard` should add AWS later without stranded flows. |

## Transcript — installer + wizard

Identical to A01 until hosting. **Skip for now** (explicit: "connect later via
`/yoke onboard` or re-run"). Apply. Hand-off.

## Transcript — `/yoke onboard` (first run)

Empty folder (wizard created git repo). Strategy for the client product.
Profile proposal includes `aws-admin` + stage+prod + `production-deploy`.

**Correct operator adjustment:** hosting deferred; **no** environment
registration; **no** `deployment-flows create`; `deploy_defaults` unset;
`domain-setup=not-needed`; `infra-apply-first-deploy=deferred`. Seed issues
with omitted `--deployment-flow`.

**Incorrect rubber-stamp:** step 5 still runs because entry is "hosting
verified **or explicitly deferred**". That is the crux: deferred hosting does
not skip environment/flow creation in the skill text.

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

**Onboard:** no test question. CURRENT-PLAN will name client tickets, not a
reusable QA plan, so seed will not attach one.

**Ask that should happen:** scaffold vs attested no-tests before any item
can hit reviewing-implementation. Recommend scaffold if they accepted
`webapp-scaffold`; else attest no-tests.

## Crux

| Requirement | Declare | Refusal | Instead |
|---|---|---|---|
| Future AWS | Hosting skip + profile "defer infra" | Do not create persistent flows while deferred | Merge-only or empty default until apply succeeded |
| Deploy on items | Idea uses `deploy-defaults get` | If get returns a flow, Usher Route B / exit 7 on skip-deploy | Keep defaults empty until hosting verified |
| Migration | Still N/A | — | Add `migration_model` when a DB exists |

Ledger: G-execution-profile-no-hosting-still-envs, G-no-deploy-default-flow, G-test-setup-unasked, G-no-tests-posture, G-qa-plan-needs-env.
