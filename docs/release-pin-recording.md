# Release-pin recording

After a deployment reports terminal success, its project-scoped
`deployment_ci` identity may record the served version without receiving
generic project-settings administration:

```bash
yoke release-pin record --project <project> \
  --environment <name> --pin <version>
```

The server resolves the environment name against the project registry, while
the project's `release_pin.desired_pin_path` selects the one scalar leaf in
`environments.settings`. Numeric keys and settings paths are not accepted from
the CLI. Missing capability, unregistered environment, or path configuration
fails closed. If the configured terminal
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
not supply a default path or environment name.

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

`probe_url_path` selects the scalar URL from the named environment's settings.
`served_pin_response_path` selects the scalar pin from that probe's JSON body.
`--environment` accepts only a name in the project environment registry.
The desired value still comes only from `desired_pin_path`. An unknown name
fails with USAGE that lists the registered environment names.

```bash
yoke release-pin verify --project <project> --environment <name>
```

Verification exits nonzero when either verification key is absent, either
environment-settings value is unset or non-scalar, the probe fails, the
configured response leaf is absent or non-scalar, or the desired and served
pins disagree. Global machinery supplies no target name, environment id,
settings path, probe URL, or response-field fallback. Numeric environment keys
remain internal and never appear in a receipt or command.

## Hosted release ordering

The Yoke `platform-release-bridge` switches to the Platform-scoped
`deployment_ci` token, dispatches Platform's promotion workflow, and waits for
that run to report terminal success. Only then does the same outer job record
the version through `yoke release-pin record`. The record command's successful,
non-empty receipt is the final job gate: a missing declaration, authorization
denial, mutation refusal, or missing receipt keeps the outer release red.

The bridge's `target_environment` input is the **registered environment name**,
which the deploy pipeline resolves from the run's typed environment reference
through the `{target_environment}` stage-input placeholder. That same name is
what `--environment` receives and what Platform's promotion workflow accepts;
the bridge performs no environment-vocabulary translation.

Platform's promotion workflow owns branch materialization, deployment, and
failure restoration. It carries no control-plane settings token and contains
no desired-pin writer. This keeps one writer at the outer success boundary and
prevents a failed inner deployment from advancing desired authority.
