# Project test environment

A project's test environment is two declarations, not a wrapper default:

- Capability `test_environment` — `uv_project`, `uv_extras`, `uv_groups`
  (comma-separated). Lane prepare and the test wrappers install and run
  that selection.
- Project Structure `test_roots` — the trees impacted selection and the
  generic runner sweep. Absence is the named verdict
  `unsupported_project_test_roots`, never another project's anchors.

Read the live values:

```text
yoke projects capability-settings get --project <slug> --cap-type test_environment
yoke project-structure get --project <slug> --family test_roots
```

An absent or empty capability is the default: `uv sync --frozen` and
`uv run --frozen python3` with no extra-selection flags. A nested
`uv_project` is passed as `uv --project <path>` only when that path is
itself a uv project from the current working directory.

Sanctioned run surface:

```text
yoke watch pytest -- <pytest args>
```

Yoke's own checkout keeps the seeded `test_roots` triple
(`runtime/api/`, `runtime/harness/`, `tests/`) and the default sync
until an operator declares otherwise. PYTHONPATH injection of
`PACKAGE_SRC_RELS` applies only to a yoke-shaped tree (the
`packages/yoke-core/src/yoke_core` marker).
