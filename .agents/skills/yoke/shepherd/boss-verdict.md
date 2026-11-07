# Shepherd — Boss review

Dispatch boss with ref, edge, caveats and feedback; after two
`[UNPARSEABLE_BOSS_OUTPUT]` on an edge, use a stronger configured model.

## Parse and persist

Parse `VERDICT: READY|NOT_READY|CAVEATS`; else loose wording; else one
tool-less extraction; else NOT_READY `[UNPARSEABLE_BOSS_OUTPUT]`. EDGE is the pinned
Shepherd verdict key: source_to_target with stage hyphens replaced by underscores
(for example `planning_to_plan_drafted`). Persist once:
```bash
yoke shepherd verdict --item ITEM --transition EDGE --worker WORKER --verdict VERDICT --caveats "{reason or numbered caveats}" --json
```
Dispose each caveat (RESOLVED only for an edit just made), then write
DEFERRED/ANALYZED under an EDGE heading in `shepherd_caveats` (`yoke items
structured-field section-upsert`) and in any task body a caveat names:
```bash
yoke shepherd caveat-disposition --item ITEM --transition EDGE --attempt {attempt} --caveat-num {caveat_num} --caveat-text "{caveat}" --disposition RESOLVED --resolution-details "{edit}" --verdict-id {verdict_id}
```

## Route the verdict

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
