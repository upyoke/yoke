# Doctor — Results and Repair Limits

- Exit 0: no FAILs; 1: at least one FAIL; 2: missing/invalid explicit scope.
  The watcher preserves the engine status.
- GitHub-dependent HCs resolve the project's verified App binding through
  `project_github_auth.resolve_project_github_auth` and use REST/GraphQL with
  short-lived installation tokens. Host gh is not required. Sync checks
  delegate internally to resync, forwarding `--fix`.
- `--fix` applies deterministic repairs and may edit many paired GitHub issues.
  Inspect a read-only report and confirm acceptable volume on a long-stale
  installation first. It never edits code, agent prompts or skill files.
- `HC-doc-health` findings (missing READMEs, broken links, stale docs and
  undocumented features) require manual attention.
- `HC-deferred-items` checks done epics for UNFILED/untracked deferrals; file
  through `/yoke idea` and update their Deferred Items section.
- Project checks follow declared capabilities, environments and workflow
  definitions: repository/App readiness, stale worktrees, VPS/health endpoints,
  secrets and deployment-flow state as applicable. An unknown project emits a
  warning and skips project-specific checks. Keep N/A reasons/counts.
- Run periodically or after significant changes. Log raw findings; normal
  work-item delivery owns nontrivial repairs.
