# Architect — Hard Constraints

Apply before writing the technical plan, task specs or worktree plan.

1. **Session-fit sizing.** Each task fits one session without compaction:
   XS <10k tokens, S 10–30k, M 30–60k, L 60–100k (scrutinize). Split anything
   larger; XL is never allowed. Beyond about 20 tasks, propose splitting the
   epic with a rationale.
2. **One concern per task.** Split unrelated subsystems; a migration, a large
   test suite or an independent documentation batch each gets a coherent owner.
   Splitting never drops required tests or docs.
3. **Tests, docs and contracts.** Every task specifies its test and
   documentation work and its exact provided and expected interfaces.
4. **Traceability.** Map every spec requirement (FR-N, or R-1… for plain-bullet
   specs) to epic acceptance criteria and every epic criterion to task criteria
   in the FR Traceability table. An unmapped requirement needs a task or an
   evidence-backed Coverage Note.
5. **Semantic anchors.** Point at functions, classes, headings, markers or
   unique literals, never line numbers.
6. **Same-file sequencing.** Tasks in one lane that edit the same file declare
   a dependency, foundational task first, and are listed under Same-file
   modifications. Any ordering, in or across lanes, is a task dependency; plan
   prose alone does not hold.
7. **Lane independence.** List every touched file. Logically coupled files
   (types and handlers, schema and migration) share a lane. Dependent same-hunk
   edits never span lanes. Generated files (locks, build output) resolve on
   merge and stay out of authored overlap checks.
8. **Live-state tags.** A criterion on a live database, deployment, service or
   shared state carries exactly `[READ-ONLY]` or `[APPLY-MUTATION]`. Untagged
   means read-only, so a mutation needs the tag and its recovery or rollback.
9. **Packs first.** Before planning a reusable script, workflow, deployment or
   infrastructure capability, check `yoke packs list`. A changed pack ships as a
   new version that projects preview before updating.
10. **File Budget.** When enabled, name each planned file, its single
    responsibility and its headroom, and decide before planning ends how a file
    near the authored-file limit is split.
11. **Documentation.** Cover every doc that teaches the changed behavior —
    README, `AGENTS.md`, the command catalog, skills and other linked docs —
    following `.yoke/docs/documentation/index.md`, and name each one in the task
    so the Tester has a target.
