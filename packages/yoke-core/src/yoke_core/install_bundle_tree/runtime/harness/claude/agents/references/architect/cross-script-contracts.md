## Cross-Script Contracts

Include this task section only when a task changes a command's structured
data, moves inline work into a subprocess, or changes how errors propagate.
Both the providing and the consuming task state the same contract.

- **Data:** the registered command, its arguments and formats, and its output
  JSON paths, columns and exit codes, including any non-obvious nesting.
- **Subprocess:** the inline operation replaced, the command that replaces it,
  the environment variables it must inherit (cite where they are set today)
  and its working directory. A missing command is a reported gap, never an
  invented internal module call.
- **Errors:** the old handling, the new propagation and the caller's guard.
