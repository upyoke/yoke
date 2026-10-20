# Onboard Steps 6–7: Domain And Infra Apply

No host: mark both rows not-needed or deferred; go to step 8.

Step 6: set `domain.mode=default-subdomain` and `domain.hostname` on each
environment (`yoke projects environment-settings merge`).

Step 7, managed deploys only: show the full Pack preview, ask `[y/N]`
(default No records `deferred`). After yes, read `.yoke/docs/agents/rules/delivery.md`,
apply, deploy stage, smoke. Failure: keep it up, write `blocked`, no retry.
