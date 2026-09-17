# /yoke doctor — exit codes, --fix scope, and check notes

## Notes

- Doctor exits 0 if no FAILs and 1 if any FAILs (the watcher wrapper at `yoke watch doctor` preserves this exit code). Use the exit code to determine overall health.
- GitHub-dependent health checks (sync-completeness-legacy, orphan/missing/comment-sync HCs) resolve the project's verified App binding through `yoke_core.domain.project_github_auth.resolve_project_github_auth` and call GitHub REST/GraphQL with a short-lived installation token — they do NOT require the host `gh` CLI. Bidirectional sync HCs delegate detection and repair to the internal resync engine in doctor format, which uses the same resolver. The doctor engine forwards `--fix` automatically; the agent never runs a host shell-out itself.
- The `--fix` flag only repairs trivial, deterministic issues. It never modifies code, agent prompts, or SKILL.md files.
- Bulk-mutation awareness: a single `/yoke doctor --fix` invocation can push large numbers of GitHub edits (every body, title, label, and state drift on every paired item). Before running `--fix` on a long-stale install, do a read-only pass first and confirm the mutation volume is acceptable.
- Run `/yoke doctor` periodically or after significant changes to catch drift early. This is part of Ouroboros — Yoke's self-improvement system.
- HC-doc-health (Documentation health audit) findings are not auto-fixable. Missing READMEs, broken links, stale docs, and undocumented features require manual attention.
- HC-deferred-items (Deferred items enforcement) scans done epics for UNFILED deferred items and untracked deferral language. Not auto-fixable — requires filing follow-up items via `/yoke idea` and updating the epic's `## Deferred Items` section.
- **Project-specific checks:** When a project other than `yoke` is specified, doctor runs generic project checks (repository and App binding readiness, stale worktrees) plus checks selected from that project's capabilities, environments, and workflow definitions. These may include VPS reachability, GitHub Actions secrets, deployment flow state, health endpoints, and orphaned worktrees. If the project is not found in the DB, a warning is emitted and project-specific checks are skipped.
