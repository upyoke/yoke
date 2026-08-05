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
environment owned by another project is refused. Recording the same pin again
is a successful no-op.

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

## Hosted release ordering

The Yoke `platform-release-bridge` switches to the Platform-scoped
`deployment_ci` token, dispatches Platform's promotion workflow, and waits for
that run to report terminal success. Only then does the same outer job record
the version through `yoke release-pin record`. The record command's successful,
non-empty receipt is the final job gate: a missing declaration, authorization
denial, mutation refusal, or missing receipt keeps the outer release red.

Platform's promotion workflow owns branch materialization, deployment, and
failure restoration. It carries no control-plane settings token and contains
no desired-pin writer. This keeps one writer at the outer success boundary and
prevents a failed inner deployment from advancing desired authority.
