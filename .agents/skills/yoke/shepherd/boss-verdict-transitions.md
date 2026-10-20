# Shepherd — Route the Verdict

READY passes; CAVEATS after every disposition. NOT_READY retries below
MAX_ATTEMPTS, then BLOCKED; never force-pass. The final review moves planning
tasks to plan-drafted. First edge: set `deployment_flow` from the spec's
Flow, and add a requirement per checkbox AC lacking one (list first; adds
duplicate; no ACs: one blocking `implementation_review`, `seeded_default`).
QA_STAGE is the first later qa_verification stage:
```bash
yoke qa requirement add --item ITEM --qa-kind ac_verification --qa-phase verification --workflow-transition QA_STAGE --blocking-mode blocking --requirement-source ac_derived --success-policy all-pass
```
