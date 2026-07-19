# Smoke Testing Pack

Provides a dispatchable post-deployment GitHub Actions smoke workflow.

## Flow integration

The workflow's `yoke_dispatch_id` input is part of its delivery contract. The
project's `.yoke/deployment-flows.json` must declare it on the smoke stage:

```json
{
  "name": "smoke",
  "executor": "github-actions-workflow",
  "workflow": "<project>-smoke.yml",
  "dispatch_correlation_input": "yoke_dispatch_id"
}
```

This lets Yoke recover a lost dispatch response and attach evidence to the
exact workflow run instead of guessing by branch or commit.

## Project-specific work

- Choose meaningful public and authenticated paths, expected responses, and
  timeouts.
- Connect any non-public checks to the project's supported test identity.
- Decide which failures block deployment completion and which only alert.
- Prove dispatch correlation and failure reporting from the real deploy flow.
