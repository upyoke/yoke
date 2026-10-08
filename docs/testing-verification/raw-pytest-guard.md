# Raw pytest invocation detection

The admission guard distinguishes executable shell sources from argv data.
Shared quote-aware pipeline boundaries and compound-prefix classification
feed pytest argv recognition. Quoted pipes, semicolons and search patterns
stay arguments. A search followed by raw pytest still receives the raw
invocation's disposition.

Whole-surface raw sweeps deny; narrower directory and pathless sweeps advise;
file-scoped runs remain unmatched. Suppression remains audit-only. Each
invocation owns its admission: quoting a watcher name, or running a watcher
in a sibling statement, cannot admit a separate raw test command.

Supported launchers include environment assignments, env, nice, time,
command, exec, uv run, poetry run, pdm run, rye run, hatch run and the source
development wrapper. Python module detection stops at a script or -c operand;
those arguments cannot invent a Python module invocation.

Shell -c, eval, literal echo/printf pipelines into shells, here-strings and
executable heredoc bodies are inspected as shell source. Active command,
backtick and process substitutions are inspected separately, including
inside double quotes and wrapper arguments. Single quotes and escapes
preserve literal text.

Direct cat/Python heredocs and the registered item Progress Log and structured
field stdin writers consume data. Quoted delimiters keep their bodies literal;
unquoted bodies still execute substitutions, which are inspected. Piped,
launcher-wrapped or unknown heredoc readers keep conservative inspection.

This is static invocation recognition, not a shell or Python interpreter.
Variable-built commands, sourced files, arbitrary program behavior and
general printf formatting are not reconstructed. Unresolved quoting or
excessive nesting with pytest evidence produces an advisory naming the
unresolved syntax and the watcher recovery. No unknown form receives a
blanket wrapper exemption.

## Replay evidence

Use bounded registered event/tool-call reads over a fixed UTC window.
Recover full original payloads from accessible session captures or transcripts,
joined by session and tool-use identity, or a unique matching command/time
correlation. Record the strength of that correlation. Command summaries and
denial snippets are bounded projections, not full originals.

Separate guard disposition from execution outcome. Independently assign
expected classifications from the entire original payload, including commands
after heredoc terminators. Record historical revisions, retention and missing
context; absence of telemetry proves nothing. Preserve shell syntax while
redacting secrets. Keep unavailable originals or uncertain expectations
inconclusive.

The pure replay utility compares a verified baseline with candidate source:

```text
yoke dev run -- python3 -m runtime.api.tools.raw_pytest_guard_replay --baseline-ref REF --corpus CAPTURE.json --output COMPARISON.json
```

The corpus contains window bounds and rows with original command, independently
assigned expected severity (silent, sweep or full), evidence identity and
explanation. The utility never executes archived commands, invokes their hooks
or emits their telemetry. Inspect every changed decision and retain correct
admissions and denials as minimized regression fixtures.

For candidate-bound post-deploy acceptance, run
`python3 -m runtime.api.tools.raw_pytest_guard_replay --acceptance`.
It evaluates a harmless quoted search and a controlled full-surface raw command
through the candidate guard, reports its module origin and decisions, and
launches no tests.
