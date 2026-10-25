# Conduct — several tasks

Lists: `next_offset` → `--offset`; keep filters.

If `parallel_subagents` in `.yoke/harness/<harness-dir>/manifest.json` is
`supported`, dispatch all eligible Engineers at once; else one at a time, noted once in
the Progress Log.
When path claims are on, give each Engineer and Tester:

```text
yoke claims path list --item PREFIX-N --state active --json
```

As each Engineer returns, finish its [loop](engineer-tester-loop.md) without
waiting. After each PASS, unless --no-chain, run `epic-dispatch-chain advance`
on that chain and every idle chain; activate each returned task
([entry-activation-resolution.md](entry-activation-resolution.md)) with fresh
context and counters, then dispatch it. --no-chain: report the next task and
go to [cleanup-report.md](cleanup-report.md). All
`chain_complete`: [simulation-gate.md](simulation-gate.md). Waiting with
nothing running: halt for authoring repair.
