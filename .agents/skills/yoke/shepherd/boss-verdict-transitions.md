# Shepherd — Route the Verdict

READY passes; CAVEATS after every disposition. NOT_READY retries below
MAX_ATTEMPTS, then BLOCKED; never force-pass. A pass transitions this edge:
```bash
yoke lifecycle transition ITEM --from EDGE_SOURCE --to EDGE_TARGET --reason "Shepherd review passed"
```
The final review moves planning tasks to plan-drafted. First edge: set
`deployment_flow` from the spec's Flow (`yoke items scalar update ITEM
--field deployment_flow --value FLOW`), and add a requirement per checkbox AC
lacking one (list first; adds duplicate; no ACs: one blocking `implementation_review`, `seeded_default`).
QA_STAGE is the first later qa_verification stage:
```bash
yoke qa requirement add --item ITEM --qa-kind ac_verification --qa-phase verification --workflow-transition QA_STAGE --blocking-mode blocking --requirement-source ac_derived --success-policy all-pass
```
