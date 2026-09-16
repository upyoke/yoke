# Idea — Infer Deployment Flow

Called from [infer-and-create.md](infer-and-create.md) §b. Owns the intake
assignment rule: look up the workflow-specific default, then the project
default, then decide whether to pass `--deployment-flow`. Never store the
literal `none`. After the item is claimed, delivery evidence follows
[delivery-requirements.md](delivery-requirements.md).

**This lookup MUST run before deciding `_deployment_flow`.** Skipping it
is wrong.

Task stays exempt: leave `_deployment_flow` empty even when a mapping still
names a flow.

```bash
_mechanics=$(yoke workflows mechanics get --json) || {
  echo "Cannot read workflow mechanics."
  exit 1
}
_project_default_flow=$(yoke project-structure deploy-defaults get \
  --project "${_project}") || {
  echo "Cannot read project deploy-defaults."
  exit 1
}
```

Empty stdout from deploy-defaults with exit 0 means no project default.
From `_mechanics`, take `delivery_defaults[]` for this `_project` and the
inferred `_workflow` when that row exists; that id is `_candidate_flow`.
Else `_candidate_flow` is `_project_default_flow`.

When `_candidate_flow` is empty, omit `--deployment-flow`. That omission
**inherits** the project/workflow default when a later resolver (release
membership included) reads it. It does not waive delivery and it does not
make the item merge-only. A docs/process/research title is not a merge-only
exemption.

When the lookup names a flow id, read the registered definition. Classify
by its fields, never by an id suffix:

```bash
_candidate_json=$(yoke deployment-flows get "${_candidate_flow}" --json) || {
  echo "Cannot read deployment flow ${_candidate_flow}."
  exit 1
}
```

Use `status`, `target_tier`, `target_environment`, and
`definition_schema_version` from that document.

- Disabled: not assignable.
- Serving runtime cannot execute that `definition_schema_version`: omit
  the assignment, keep the definition disabled, and report it. Do not
  invent a weaker substitute.
- Empty/`null` `target_tier` is merge-only; `persistent` and `ephemeral`
  come from the same fields. An id ending in `-internal` is not route
  authority.

Attach the looked-up id when it is active and executable. Print
`Deployment flow: {_deployment_flow} (inherited default)`.

If the operator named an environment, screenshot, or verdict the candidate
cannot satisfy, do not attach it and do not rewrite shared defaults. Select
or configure a suitable **item** flow per
[delivery-requirements.md](delivery-requirements.md).

An explicit merge-only request selects a registered merge-only definition
(`target_tier` empty) from `yoke deployment-flows list --project P --json`
then `get`. Do not treat a title as merge-only.

## Fallback

Runs only when both lookups printed nothing. List **deployment flows**,
not workflow definitions:

```bash
_flow_list=$(yoke deployment-flows list --project "${_project}" --json) || {
  echo "Cannot list deployment flows."
  exit 1
}
```

Empty list → omit `--deployment-flow` (inheritance, not a waiver) and
report that no default is configured. Do not invent a flow from a name
suffix. If the request still needs a flow (explicit merge-only, named
environment, screenshot, approval) and no valid definition exists, report
the missing or unsupported setup.

If a flow applies, set `_deployment_flow` to its registered id. NEVER store `none`.
