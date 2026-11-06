# Refine — Review Rubric

List verbatim **Decisions to preserve** and **User questions and evidence
to preserve**. Check:
- Complete outcome: wiring, errors, cleanup, docs; no unrelated scope.
- Removals: real search plus zero-residue ACs; migrations stay.
- Open questions that change interfaces get an answer or default.
- Reuse named, or the search that found none; testable `- [ ] AC-N: ...`.
- File Budget: use a dash list with each path in backticks, one physical file
  per row, including a separate row for every generated copy. Record current
  lines, remaining headroom (350 minus current), and at-or-over-limit: true|false
  (true at 350 or above). New files use current 0 lines. Include every path in
  the claim when path claims are enabled; 300+ line files need a split.
  Example row:
  - `src/example.py` — current 120 lines; remaining headroom 230; at-or-over-limit: false
- QA requirements only for verification outside attached plans.
- DB claim matches DB prose ([db-claim-classification.md](../idea/db-claim-classification.md)).
- Browser QA: [Where a Browser case runs](../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs).
