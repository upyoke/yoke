"""Fill-me-in scaffold renderers for the ``.yoke`` project contract.

Split from :mod:`project_contract` (which owns the bundle assembly and
policy/appearance renders) to respect the authored-file line cap. Every
renderer here produces operator-editable starting content parameterized
by the project display name; the seed-if-missing install policy makes
the files project-owned the moment they land.
"""

from __future__ import annotations

def render_file_line_exceptions(display_name: str) -> str:
    return """# Project file-line exceptions.
#
# `yoke check file-line` enforces the authored-file line limit from the
# DB-backed project-policy capability (`file_line_limit`, default 350).
# Add one repo-relative glob per line for files that are intentionally
# unsplittable or non-authored data.
#
# Blank lines and lines starting with # are ignored. Use forward slashes.
# Do not use this to avoid splitting normal source code.
#
# Example:
# docs/generated-reference/**
"""


def render_test_inventory(display_name: str) -> str:
    return f"""# Test Inventory: {display_name}

Yoke command definitions in the authoritative DB own executable test command
records. This file explains how agents and operators should interpret those
surfaces for {display_name}.

## Scopes

- `quick` - focused checks for the changed surface.
- `full` - broader local verification before review or merge.
- `smoke` - deployed-target health checks when the project has a deploy flow.
- `e2e` - deployed-system verification when a real E2E suite exists.

Update this file when test intent changes. Update DB command definitions when
the executable commands change.
"""


def render_template_deviations(display_name: str) -> str:
    return f"""# Template Deviations: {display_name}

No project-specific template deviations are recorded yet.

When a change touches a reusable capability, first decide whether the change
belongs in the shared template, in {display_name}, or in both — and record
approved differences here.
"""


def render_deploy_runbook(display_name: str) -> str:
    return f"""# Deploy Runbook: {display_name}

How {display_name} gets deployed, for humans and agents working in this repo.
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
"""


def render_deploy_checklist(display_name: str) -> str:
    return f"""# Deploy Checklist: {display_name}

Run through before activating deploy flows for a new environment.

- [ ] Project capabilities/settings are populated in the Yoke DB.
- [ ] Deployment flows name the intended target environment.
- [ ] Provider credentials resolve through capabilities only (never
      ambient shell).
- [ ] Smoke checks are recorded as deployment or QA evidence.

Add project-specific readiness items as they become real:

- [ ] TODO
"""


def render_recovery_runbook(display_name: str) -> str:
    return f"""# Recovery Runbook: {display_name}

What to do when {display_name}'s runtime or data plane needs recovery, for
humans and agents. Fill in as the infrastructure takes shape.

## State surfaces

TODO: name the authoritative data stores, their backup story, and where
infrastructure state (e.g. IaC backends) lives.

## Restore procedure

TODO: how to restore each state surface, and in what order.

## Break-glass access

TODO: how an operator reaches the infrastructure when Yoke runtime
surfaces are unavailable.
"""


__all__ = [
    "render_deploy_checklist",
    "render_deploy_runbook",
    "render_file_line_exceptions",
    "render_recovery_runbook",
    "render_template_deviations",
    "render_test_inventory",
]
