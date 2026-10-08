# Proposing level changes

`yoke models level-proposal` reads the current catalog revision and the
universe levels and returns every change it can extrapolate:

- an option whose model the catalog supersedes is retired and its successor
  added at the same position, carrying the option's surface, selector shape,
  effort, and context window;
- an option whose effort or context window the model's published values do
  not include moves to the nearest published effort the surface accepts, or
  to the model's default window.

It also lists `unverified` options (model not researched, or no published
efforts or windows) and `unplaced_models` (catalog models no level launches
and nothing supersedes). Placing an unplaced model, moving an option between
levels, or retiring one is the refresh author's judgment: extrapolate from
where today's options sit and what is known about the new and old models,
then pass the complete change list on `--stdin`, starting from the generated
`changes` in `--json` output. Each change is one of:

```json
{"kind": "add", "level": "SENIOR", "option": {"surface": "...", "model": "...", "reasoning_effort": "...", "context_window_tokens": null}, "position": 0, "reason": "..."}
{"kind": "move", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "to_level": "JUNIOR", "reason": "..."}
{"kind": "retire", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "reason": "..."}
{"kind": "change", "option": {"surface": "...", "model": "...", "reasoning_effort": "..."}, "reasoning_effort": "high", "context_window_tokens": null, "reason": "..."}
```

Any resulting option whose effort or context window its model's published
values contradict is refused by name (`level_option_reasoning_effort_unpublished`,
`level_option_context_window_tokens_unpublished`); `yoke universe levels set`
refuses the same documents. Present the proposal to the operator. Only after
approval, store it:

```bash
yoke models level-proposal --levels-only [--stdin < changes.json] > /tmp/levels.json
yoke universe levels set --stdin < /tmp/levels.json
```
