# Conduct — several tasks

If `parallel_subagents` in `.yoke/harness/<harness-dir>/manifest.json` is
`supported`, dispatch all eligible Engineers at once; else one at a time, noted once in
the Progress Log.
When path claims are on, give each Engineer and Tester:

```text
yoke claims path list --item PREFIX-N --state active --json
```

As each Engineer returns, finish its [loop](engineer-tester-loop.md) without
waiting. After each PASS, unless --no-chain, run `epic-dispatch-chain advance`
on that chain and every idle chain and dispatch what returns. All
`chain_complete`: [simulation-gate.md](simulation-gate.md). Waiting with
nothing running: halt for authoring repair.
