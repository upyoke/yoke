# Idea — Infer Deployment Flow

Called from [infer-and-create.md](infer-and-create.md) §b. Owns the intake
assignment rule: look up the project default first, then decide whether to
attach it. Never store the literal `none`.

**This lookup MUST run before deciding `_deployment_flow`.** Skipping it and
jumping to fallback inference is wrong.

```bash
_project_default_flow=$(yoke project-structure deploy-defaults get --project "${_project}" || true)
```

Empty stdout means no default — go to **Fallback** below and omit
`--deployment-flow`.

When the lookup prints a flow id, classify it before assigning:

```bash
_default_tier=$(yoke deployment-flows get "${_project_default_flow}" --field target_tier || true)
_default_env=$(yoke deployment-flows get "${_project_default_flow}" --field target_environment || true)
```

`target_tier` is `persistent`, `ephemeral`, or empty (merge-only). A
`-internal` suffix is Usher Route A regardless of tier.

Attach the default when any of these hold:

- the flow id ends in `-internal`
- `_default_tier` is empty (merge-only)
- the operator or title is deploy work

Omit `--deployment-flow` when the default is persistent
(`_default_tier` is `persistent` or `_default_env` is non-empty) and the
item cannot use that environment:

- title/body is clearly non-delivery (docs, research, process), or
- hosting is not healthy: `_default_env` is empty on a persistent flow
  (no resolvable target environment)

Otherwise attach the default.

On attach: set `_deployment_flow` to the looked-up id and print
`Deployment flow: {_deployment_flow} (project default)`.
On omit: leave `_deployment_flow` empty and print
`Deployment flow: (omitted — persistent default not applied)`.

## Fallback

Runs only when the lookup printed nothing:

```bash
_flow_list=$(yoke workflows definition get --project "${_project}" 2>/dev/null || true)
```

- empty list → leave `_deployment_flow` empty
- exactly one non-internal flow → auto-select it
- multiple flows → infer from context (deploy work → that flow;
  docs/process → omit). Ask only if genuinely ambiguous.

If a flow applies, set `_deployment_flow` to its registered id. If none
applies, leave it empty. NEVER store `none`.
