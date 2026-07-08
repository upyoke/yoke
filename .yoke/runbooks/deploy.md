# Deploy Runbook: Yoke

How Yoke gets deployed, for humans and agents working in this repo.
Yoke's authoritative DB owns deploy execution (flows, capabilities,
environment settings); this file carries the context those records cannot:
the why, the order, the gotchas.

Fill in the sections below as the deploy story takes shape — agents working
deployment tickets should keep this current.

## Targets and environments

TODO: name the environments (prod/stage/...), where each runs, and what
promotes between them.

## Build and release

TODO: how a release artifact is produced (image/bundle/binary), where it
lands, and how it is versioned.

## Deploy procedure

TODO: the happy-path deploy, step by step, naming the Yoke flow or
commands that execute it.

## Verification

TODO: smoke checks and health surfaces that prove a deploy landed.

## Rollback

TODO: how to roll back, and what state (data, migrations) constrains it.
