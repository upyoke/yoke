## Cross-script contracts

Read this when two tasks exchange anything — a file, a schema, a command, a
return shape. It is the full contract vocabulary and worked examples.

## Cross-Script Contracts
(Conditional — include ONLY when the task calls existing scripts that produce/consume structured data, replaces inline operations with subprocess calls, or changes error propagation models. Omit entirely for tasks with no cross-script boundaries.)

### Data Structure Contracts
For each existing command this task calls that produces or consumes structured data (JSON envelopes, DB row structures, config formats), document the schema. Use the registered `yoke ...` command named in the packet/Atlas, or a project-provided command from the dispatch context:
- Command: registered `yoke ...` command or project-provided command
  - Input: describe expected arguments and their formats
  - Output: describe the output schema (JSON paths, DB columns, exit codes)
  - Key detail: note any non-obvious nesting, wrapping, or transformation the script applies

### Subprocess Environment Contracts
When this task replaces inline operations (e.g., direct database-client calls) with subprocess calls, document the real registered `yoke ...` command from the packet/Atlas or the project-provided command being invoked:
- What was inline vs what is now a subprocess
- Environment variables that must be propagated (with existing pattern references)
- Working directory assumptions

### Error Model Contracts
When this task changes how errors propagate (e.g., inline `|| true` replaced by a subprocess with `set -e`), document:
- Old error model: how failures were handled before
- New error model: how failures propagate in the new design
- Guard requirements: what callers must do differently
