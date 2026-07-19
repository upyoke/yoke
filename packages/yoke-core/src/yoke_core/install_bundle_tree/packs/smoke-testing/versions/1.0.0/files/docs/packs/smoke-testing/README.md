# Smoke Testing Pack

Provides a dispatchable post-deployment GitHub Actions smoke workflow.

## Project-specific work

- Choose meaningful public and authenticated paths, expected responses, and
  timeouts.
- Connect any non-public checks to the project's supported test identity.
- Decide which failures block deployment completion and which only alert.
- Prove dispatch correlation and failure reporting from the real deploy flow.
