# Architect — Hard Constraints

Read/apply before technical plan, task specs or worktree plan.

## Hard Constraints

1. **Session-fit sizing.** One session without compaction per task: XS<10k
   tokens, S10–30k, M30–60k, L60–100k (scrutinize), XL>100k never allowed: split.
2. **Worktree independence.** List every touched file. Cross-lane conflicts
   require partition repair or justified attested coordination; no dependent
   same-hunk overlap across lanes. Programmatic overlap check verifies coverage.
3. **Logical dependency groups.** Types/handlers, schema/migrations and other
   logically coupled files share one lane and explicit group in worktree plan.
4. **Sequential within, parallel across.** Default multi-lane fan-out where
   budget/scope allows independent groups. Single-lane needs explicit blocker:
   linear live-surface DAG, semantically dependent same hunk, or <=3tasks whose
   overhead exceeds saved time. Shared additive settings are not inherently
   blocking; disjoint claims and attested coordination_only permit independence.
   Worktree Decomposition justifies shape; no convenience/shared-claim excuse.
5. **Tests/docs/contracts mandatory.** Each task specifies test and documentation
   work and exact provided/expected interfaces.
6. **Epic ACs mandatory.** Technical Plan Acceptance Criteria maps every spec
   requirement to epic ACs and every epic AC to task ACs; prose-only coverage
   is insufficient. FR Traceability provides structural proof.
7. **FR-to-task traceability.** FR Traceability table sits between Task Summary
   and Task Dependency Graph. Enumerate all FR-N; verify mapped task AC intent.
   Unmapped FR needs task or verified Coverage Note exclusion. Plain-bullet specs
   use R-1 etc. Never emit unmapped requirements.
8. **Epic size.** Beyond about20tasks propose sequential epic split with rationale.
9. **Generated files.** Flag locks/compiled/build artifacts auto-resolve on merge;
   exclude generated output from authored overlap checks.
10. **Single responsibility.** One primary concern per task. Split unrelated
    subsystem/concern conjunctions: migrations, substantial test suite and
    independent documentation batch need coherent ownership. Required tests and docs
    remain covered; splitting does not silently omit them.
11. **Semantic anchors.** Reference functions/classes/headings/variables/markers/
    unique literals, never changing source line numbers.
12. **Same-file sequencing.** Within one lane declare dependencies, foundational
    task first; later insertion anchors reference its added content. List file,
    tasks and required order in Same-file modifications. Prevent parallel edits
    assuming incompatible baselines.
13. **Live-state AC tags.** Exactly `[READ-ONLY]` or `[APPLY-MUTATION]` on live DB/
    deployment/service/shared-state ACs; no MUTATE/WRITE aliases. Untagged defaults
    read-only, so mutation needs explicit intent and domain safeguards.
14. **Pack-first capabilities.** Search existing focused packs before reusable
    scripts/workflows/deployment/infra. New capability: immutable version bundle
    with files/settings/dependencies/docs/verification/project gaps. Changed
    capability: new version plus preview-first project update. Installed files
    are project-owned, runtime output scratch/deploy-run; project settings in DB,
    policies/docs in project .yoke. No project output in Yoke source, forced
    upstream customizations, drift policing/pruning or whole-project sync.
15. **File size.** Every authored tracked file<=350lines, design<=300. Plan splits
    before large responsibility exceeds cap; universal file_line_check applies.
16. **File Budget upstream and independent of claims.** Read workflows.item.get effective
    file_budget/path_claims only. required_per_task preserves task File Budget:
    named planned files, single responsibilities and headroom. Name300+line
    owners and decide split or bounded additions BEFORE planning concludes. Pair
    explicit edit paths with claims only when claims enabled. Claims-off budgets
    still size/check conflict evidence; disabled budgets do not create contracts.
    Both off: plan the full execution scope without inventing either artifact.

## Documentation File Checklist

For changed capabilities review all relevant owners, including public entrypoints:
- README.md: features, commands, layout, FAQ.
- AGENTS.md (CLAUDE.md symlink): rules/layout/counts.
- .yoke/docs/reference/commands.md: command catalog.
- .agents/skills/yoke/SKILL.md: command router.
- Every other AGENTS-linked doc and source/discovery reference to the behavior.

Include actual references in task coverage/ACs; a missing top-level doc leaves
users unaware and gives Tester no explicit verification target.
