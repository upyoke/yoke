# Simulator — System-Wide Simulation

Reference content for the canonical simulator prompt at `runtime/agents/simulator.md`. Read and follow this file when invoked with `--system` (no epic name). The system-wide mode performs a **consistency audit** across Yoke's entire codebase instead of tracing per-epic integration paths. The approach is fundamentally different: instead of checking task interface contracts and worktree visibility, you check that all of Yoke's components — agents, commands, scripts, rules, hooks, and documentation — are internally consistent and up to date.

## Gap Categories

Check for these 5 categories of system-wide gaps:

1. **Stale agent references:** Agent prompt files (`.claude/agents/yoke-*.md`) reference tool names, file paths, script names, directory structures, or command outputs that no longer match the actual codebase. Example: an agent prompt references a retired script name but the script has been renamed or removed.

2. **Stale SKILL.md references:** SKILL.md command files reference incorrect file counts, script names, file paths, directory layouts, or command names. Example: a SKILL.md says "15 scripts" but there are now 16.

3. **Cross-agent assumption mismatches:** Agent A's prompt says file X has format Y, but Agent B's prompt expects format Z. Or Agent A's output structure doesn't match what Agent B's invoking SKILL.md parses. Example: the Engineer's reflection format uses different delimiters than what the dispatch SKILL.md expects to capture.

4. **Stale hook references:** Hook scripts (`.claude/hooks/` or hooks defined in agent frontmatter) reference files, environment variables, paths, or commands that do not exist or have changed. Example: a SubagentStop hook calls a script that was renamed.

5. **Rule-implementation contradictions:** Rules in `.claude/rules/*.md` contradict the actual implemented behavior in SKILL.md files or shell scripts. Example: a rule says "always commit after every change" but a SKILL.md workflow skips commits in certain flows.

## Process for System-Wide Simulation

1. **Read all system files** provided in the context bundle: agent definitions, SKILL.md files, shell scripts, rules, hooks, and documentation.

2. **For each agent definition**, verify that every referenced path, tool name, file format, and behavioral assumption matches the actual codebase. Use Grep and Glob to spot-check claims.

3. **For each SKILL.md**, verify that file counts, script references, directory paths, and command routing match reality.

4. **For cross-agent paths**, trace the data flow between agents (e.g., Architect output → Engineer input → Tester validation) and check that formats, field names, and assumptions align.

5. **For hooks and rules**, verify that referenced files exist, scripts are executable, and rule statements match implemented behavior.

6. **Produce a gap report** using the same format as per-epic simulation (same severity levels, same structure). The output file path will be provided by the invoking command.

## Key Differences from Per-Epic Simulation

| Aspect | Per-Epic | System-Wide |
|--------|----------|-------------|
| Input | Epic tasks, worktree plan, code diffs | All agents, SKILLs, scripts, rules, docs |
| Focus | Interface contracts between tasks | Internal consistency across components |
| Tracing | Dependency edges, worktree visibility | Data flow between agents, reference accuracy |
| Auto-fix | Available (Architect fix mode) | Not available (report only) |
| Output | `qa_runs` table via `yoke workflow-item epic-task simulation-upsert` | `ouroboros/health/simulation-system-{date}.md` |
