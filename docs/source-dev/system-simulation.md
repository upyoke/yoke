# System simulation from a Yoke source checkout

This is the deep home for `/yoke simulate --system`. The skill's source-checkout
guard must pass first. The audit reports consistency gaps across Yoke itself;
it neither executes epic work nor offers auto-fix.

## Gather the audit bundle

Inventory and inspect these surfaces, labeling every included artifact by path:

- Rendered agent prompts: all `.claude/agents/yoke-*.md`, `.codex/agents/yoke-*.toml`, and `.cursor/agents/yoke-*.md`.
- Claude adapter frontmatter; inspect generated adapters for drift/hook wiring.
- Root and nested `.agents/skills/yoke/**/SKILL.md` routers and their phase maps.
- Python owners named in their operational guidance: `yoke_core.domain`,
  `yoke_core.engines`, `yoke_core.cli`, `yoke_core.tools`, `yoke_contracts`,
  `yoke_cli` and `yoke_harness`. Resolve source through declared package roots.
- All `.claude/rules/*.md` and `docs/*.md`.
- `yoke hook evaluate` ownership, `.claude/settings.json`, `.codex/hooks.json`
  and the hook-handler docstrings.

Use the inspected source as evidence. Pass each artifact once; referenced
owners need their selected implementation, rather than unrelated module bodies.
Include the actual checkout and active harness. Generated adapter paths retain
their installed names; they are views of the canonical agent source.

## Dispatch the read-only Simulator

Use the harness's `yoke-simulator` descriptor with this prompt and the bundle:

```text
Run a system-wide consistency audit for Yoke.
Mode: SYSTEM-WIDE (Ouroboros).
Checkout: {verified source root}

Audit agents, skills, Python owners, rules, hooks and documentation.
Canonical Agent Bodies:
{contents of each rendered agent prompt, labeled with its installed filename}
Claude adapter frontmatter: {labeled blocks}
Skills: {labeled root/nested routers and phase references}
Python API: {selected named owners, labeled by module path}
Rules and documentation: {labeled contents}
Hook wiring: {settings entries and handler docstrings}

Check stale agent references, stale skill references, cross-agent assumption
mismatches, stale hook references and rule/implementation contradictions.
Spot-check claims with scoped Grep/Glob/Read against this checkout.
Return verified paths, mismatches and concrete fix guidance with
[CRITICAL], [WARNING] or [NOTE] prefixes. Begin with exactly:
SIMULATION: CLEAN or SIMULATION: GAPS FOUND
SCOPE: SYSTEM
```

The PostToolUse Agent-tool hook `yoke_core.domain.reflection_capture_hook`
captures the delimited reflection envelope. Do not insert it again; an absent
reflection block does not block the report.

## Persist and report

Save the complete returned report through the source-owned helper:

```sh
yoke dev run -- python3 -m yoke_core.domain.persist_system_simulation --repo-root CHECKOUT < REPORT_FILE
```

The helper creates `ouroboros/health/` and prints the generated
`simulation-system-{YYYYMMDD}.md` path. Check exit status and read the saved
report before describing it as persisted. The report is local and gitignored;
do not stage or commit it.

Count severity-prefixed lines and display the critical/warning/note counts and
full report path. Critical gaps require `/yoke idea` and normal delivery;
warnings require review and filing when action is needed. With neither,
report a clean consistency audit. The report itself authorizes no code or
control-plane changes. Do not offer auto-fix for system-wide simulation.
