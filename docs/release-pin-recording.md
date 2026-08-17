# Release-pin recording

After a deployment reports terminal success, its project-scoped
`deployment_ci` identity may record the served version without receiving
generic project-settings administration:

```bash
yoke release-pin record --project <project> \
  --environment <target> --pin <version>
```

The server resolves both mutation coordinates from that project's
`release_pin` capability. `environment_by_target` selects the environment id,
and `desired_pin_path` selects the one scalar leaf in
`environments.settings`. Neither coordinate is accepted from the CLI. Missing
capability, target mapping, or path configuration fails closed; a configured
environment owned by another project is refused. If the configured terminal
leaf currently contains an object or array, recording refuses to replace that
container with a scalar. Recording the same scalar pin again is a successful
no-op.

The `deployment_ci` role cannot call the generic environment-settings mutation
or change the capability declaration. `infrastructure_ci` remains read-only
and cannot record pins. A project owner deliberately converges a legacy
capability before rollout:

```bash
yoke projects capability-settings merge --project <project> \
  --cap-type release_pin --set desired_pin_path=<scalar.path>
```

Configure the path for the project's own schema. Generic Yoke machinery does
not supply a default path or environment id.

## Verification contract

Live agreement checks are optional for a recording-only capability. A project
that uses `yoke release-pin verify` declares both additional coordinates in the
same capability:

```bash
yoke projects capability-settings merge --project <project> \
  --cap-type release_pin \
  --set probe_url_path=<environment.settings.url.path> \
  --set served_pin_response_path=<probe.response.pin.path>
```

`probe_url_path` selects the scalar URL from the mapped environment's settings.
`served_pin_response_path` selects the scalar pin from that probe's JSON body.
`--environment` accepts a key from `environment_by_target`, the mapped
environment id, or that environment's own `name`. The desired value still
comes only from `desired_pin_path`. An unknown token fails with USAGE that
lists the accepted keys (map keys, mapped ids, and mapped environment names).

```bash
yoke release-pin verify --project <project> --environment <target>
```

Verification exits nonzero when either verification key is absent, either
environment-settings value is unset or non-scalar, the probe fails, the
configured response leaf is absent or non-scalar, or the desired and served
pins disagree. Global machinery supplies no target name, environment id,
settings path, probe URL, or response-field fallback.

## Hosted release ordering

The Yoke `platform-release-bridge` switches to the Platform-scoped
`deployment_ci` token, dispatches Platform's promotion workflow, and waits for
that run to report terminal success. Only then does the same outer job record
the version through `yoke release-pin record`. The record command's successful,
non-empty receipt is the final job gate: a missing declaration, authorization
denial, mutation refusal, or missing receipt keeps the outer release red.

The bridge's `target_environment` input is the **registered environment name**,
which the deploy pipeline resolves from the run's typed environment reference
through the `{target_environment}` stage-input placeholder. That name is what
`--environment` receives, so a release to an environment row whose id is
`production` and whose name is `prod` records against the `prod` key rather than
failing `target_not_configured`. A dispatched workflow's own display vocabulary
is derived from the name at the step that speaks to that workflow, and never
travels back into a Yoke surface.

Platform's promotion workflow owns branch materialization, deployment, and
failure restoration. It carries no control-plane settings token and contains
no desired-pin writer. This keeps one writer at the outer success boundary and
prevents a failed inner deployment from advancing desired authority.
