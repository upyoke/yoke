# Template Deviations: Yoke

Yoke is both the product source repo and a Yoke-managed project. That is an
approved deviation from external project installs, which receive generated
agent packets, hook config, and skills without carrying Yoke product source.

## Approved Deviations

### Product source remains in the repo

`runtime/`, `templates/`, `docs/`, `.agents/`, `.claude/`, and `.codex/` are
Yoke product/source surfaces. They are not installed project-layer residue
and are not removed by the project-contract cutover.

### Local repair checkout remains valid

After cloud runtime cutover, local Yoke code remains a development, admin,
and repair checkout that speaks Postgres. Retiring local runtime authority does
not mean deleting this codebase.

### Harness-direct escape stays outside Yoke

If cloud Yoke is unavailable, Codex or Claude can still work directly on this
repository with native file/edit/test/git tools. That is a harness property,
not an installed Yoke project artifact.

## Review Rule

When a future change touches behavior that should apply to all managed
projects, update the shared template/install layer first and then instantiate
it in Yoke and Buzz. Do not make Yoke a permanent special case just because
the product source repo is also the first managed project.
