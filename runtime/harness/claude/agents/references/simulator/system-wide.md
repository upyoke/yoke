# Simulator — System-Wide Simulation

Read for --system (no epic). Audit project consistency rather than task DAG;
no Architect autofix, report only.

## Five gap categories

1. Stale agent paths/tools/formats/outputs against actual source.
2. Stale skill counts/paths/layout/commands/routing.
3. Cross-agent data-shape/field/delimiter/assumption mismatch at handoffs.
4. Hook paths/env/commands/frontmatter drift.
5. Rules contradicting implemented workflow/behavior.

Read supplied agents/skills/scripts/rules/hooks/docs bundle. Verify every cited
reference with actual source, trace agent input→output consumers and parsed
formats, check hook existence/executable routes and rule enforcement. Use same
severity/report/construct-verification contract, prefix `SCOPE: SYSTEM`.
Parent persists to supplied destination (`ouroboros/health/simulation-system-
{date}.md` for source audit); Simulator never writes files. Per-epic parent
instead persists qa_runs through registered simulation-upsert. Do not invent
epic identity or use epic autofix for source-wide audit.
