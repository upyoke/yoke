## Cross-Script Contracts

Read before authoring either side of a file/schema/command/return boundary.
Include this section only for structured-data commands, inline→subprocess
replacement, or changed error propagation; omit irrelevant boilerplate.

### Data Structure Contracts

Name actual registered packet/project command, input arguments/formats, output
JSON paths/DB columns/exit codes, non-obvious nesting/wrapping/transforms.
Both providing and consuming tasks specify the same schema.

### Subprocess Environment Contracts

State previous inline operation and new registered/project command, required
propagated environment variables with existing source patterns, and cwd
assumptions. Missing surface is a reported gap, never invented internal module.

### Error Model Contracts

Document old handling, new propagation and caller guards (e.g. ignored inline
error versus failing subprocess). Watch Out For holds remaining boundary gotchas.
