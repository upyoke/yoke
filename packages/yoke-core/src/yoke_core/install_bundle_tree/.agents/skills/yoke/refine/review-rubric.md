# Refine — Review Rubric

List verbatim **Decisions to preserve** and **User questions and evidence
to preserve**. Check:
- Complete outcome: wiring, errors, cleanup, docs; no unrelated scope.
- Removals: real search plus zero-residue ACs; migrations stay.
- Open questions that change interfaces get an answer or default.
- Reuse named, or the search that found none; testable `- [ ] AC-N: ...`.
- File Budget: one physical file per row; 300+ line files need a split.
- QA requirements only for verification outside attached plans.
- DB claim matches DB prose ([db-claim-classification.md](../idea/db-claim-classification.md)).
- Browser QA: [Where a Browser case runs](../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs).
