# Execution lane belongs to the registered session

## Decision

The session row owns `execution_lane`. Registration resolves its grouping
from the project’s `session-routing` harness/model selectors and defaults.
A caller-supplied envelope cannot change that identity. Steering assigns work
explicitly, and pinned workflow bindings select the stage skill.

## Consequences

Lane groupings remain useful for identity and roster views. Checkpoint
telemetry stored in the session envelope does not grant routing authority.
