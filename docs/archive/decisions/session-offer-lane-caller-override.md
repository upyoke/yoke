# Session registration owns execution-lane identity

## Context

A client-supplied lane can override the project grouping. Substituting a
locally guessed value for an unresolved lane made otherwise identical
sessions report different identities.

## Decision

Lane identity is stamped at registration. An explicit registration override
wins; default and unresolved sentinels yield to project selectors and harness
defaults. Session identity reads return the stored grouping.

## Consequences

Execution lanes group harnesses and models. Work assignment follows pinned
workflow bindings and explicit staffing. The former pull-based offer and
lane-permission machinery are retired; telemetry from those paths remains
historical evidence only.
