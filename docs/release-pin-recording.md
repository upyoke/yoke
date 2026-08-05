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
