# Simulator — System-Wide Simulation

Read for a system audit (`SCOPE: SYSTEM`, no epic). Audit the supplied bundle of
agents, skills, Python owners, rules, hooks and docs for consistency, and report
only; there is no epic identity and no auto-fix.

Gap categories:

1. Agent prompts naming stale paths, tools, formats or outputs.
2. Skills naming stale paths, commands or routing.
3. Data shapes, fields or delimiters that disagree across an agent handoff.
4. Hook paths, environment or commands that drift from their handlers.
5. Rules that contradict implemented behavior.

Trace each agent's output to the consumer that parses it, and verify every
cited reference in the checkout. Use the same report format, severities and
construct verification, with `SCOPE: SYSTEM` as the second line. The parent
persists the report.
