# Model Level Proposals

`yoke models level-proposal` reads current catalog and universe levels.
It replaces superseded options with successors at the same position, preserving
surface, selector shape, effort and window; unsupported effort/window changes
to the nearest published effort the surface accepts or the model default window.

It names `unverified` options (unresearched or no published efforts/windows)
and `unplaced_models`. Author judgment places, moves or retires options from
known facts/current placement. Start from generated JSON `changes`, then supply
the complete list on stdin:

```json
{"kind":"add","level":"SENIOR","option":{"surface":"...","model":"...","reasoning_effort":"...","context_window_tokens":null},"position":0,"reason":"..."}
{"kind":"move","option":{"surface":"...","model":"...","reasoning_effort":"..."},"to_level":"JUNIOR","reason":"..."}
{"kind":"retire","option":{"surface":"...","model":"...","reasoning_effort":"..."},"reason":"..."}
{"kind":"change","option":{"surface":"...","model":"...","reasoning_effort":"..."},"reasoning_effort":"high","context_window_tokens":null,"reason":"..."}
```

Proposal and levels set both refuse contradictions to published values:
`level_option_reasoning_effort_unpublished` and
`level_option_context_window_tokens_unpublished`.
Present the proposal; only operator approval authorizes storage.

```sh
yoke models level-proposal --levels-only [--stdin < changes.json] > /tmp/levels.json
yoke universe levels set --stdin < /tmp/levels.json
```
