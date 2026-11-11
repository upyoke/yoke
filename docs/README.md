# Yoke source documentation

Operator and agent documentation lives in [public/](public/index.md); it ships on the docs site and in `.yoke/docs/`. This index covers contributor documentation kept outside that public tree.

Run source commands from a claimed lane through `yoke dev run --`. Read [source-dev doctrine](source-dev-doctrine.md) before verification, release or control-plane work.

## Source guides

- [Yoke — Architecture Overview](OVERVIEW.md)
- [Subagent Reference (internal)](agents.md)
- [API observability](api-observability.md)
- [Browser Automation Substrate](browser-substrate.md)
- [CI image mirrors](ci-image-mirror.md)
- [Command resolution](command-resolution.md)
- [Event Catalog](event-catalog.md)
- [Event Contract](event-contract.md)
- [GitHub Actions workflow conditions](github-actions-gotchas.md)
- [GitHub App CI Custody](github-app-ci-custody.md)
- [GitHub App Operations](github-app-operations.md)
- [GitHub Connection Layers](github-connections.md)
- [The credentialed git environment (internal)](github-credentialed-git.md)
- [Harness Adapter Template (internal)](harness-adapter-template.md)
- [Harness Bootstrap Contract (internal)](harness-bootstrap.md)
- [Harness contributor index](harness-contributor-index.md)
- [Cursor Harness Substrate Evidence (internal)](harness-cursor-assessment.md)
- [Linux desktop config and plan-limit credentials](harness-linux.md)
- [Harness Substrate](harness-substrate.md)
- [Hook Parity Map (internal)](hook-parity-map.md)
- [Hooks Reference](hooks.md)
- [Hosted Service Identity](hosted-service-identity.md)
- [Fleet Preflight Box Identity](fleet-preflight-box-identity.md)
- [Installer Session Registration And Telemetry](installer-session-telemetry.md)
- [Contributor setup](../CONTRIBUTING.md)
- [Installation](public/start/install.md)
- [Machine registry](machine-registry.md)
- [Native instant storage](native-instant-storage.md)
- [Project installation](public/start/project-install.md)
- [Path Claims (internal)](path-claims.md)
- [Performance implementation evidence](performance-diagnostics.md)
- [Project selection in the shared app](project-selection.md)
- [Prompt Philosophy](prompt-philosophy.md)
- [Release-pin recording](release-pin-recording.md)
- [Machine Temp Scratch Paths](scratch-root.md)
- [Cross-Harness Session Identity Contract](session-identity-contract.md)
- [Source-dev doctrine — working on Yoke itself](source-dev-doctrine.md)
- [Source-Dev Worktree Cleanup](source-dev-worktree-cleanup.md)
- [State Management](state-management.md)
- [Structured Logging Standard -- Cross-Stack Event Specification](structured-logging-standard.md)
- [Testing and Verification](testing-verification.md)
- [Dashboard path routes](universe-path-routing.md)
- [Universe portability implementation](universe-portability.md)
- [Workflows](public/workflows/index.md)

- [Hosted GitHub App runtime binding](github-app-hosted-runtime.md)

## Contributor subtrees

- [browser-substrate](browser-substrate/) — Contributor material grouped by browser substrate.
- [event-contract](event-contract/) — Contributor material grouped by event contract.
- [packs](packs/) — Contributor material grouped by packs.
- [qa-platform](qa-platform/) — Contributor material grouped by qa platform.
- [releases](releases/) — Contributor material grouped by releases.
- [session-identity-contract](session-identity-contract/) — Contributor material grouped by session identity contract.
- [source-dev](source-dev/) — Contributor material grouped by source dev.
- [state-management](state-management/) — Contributor material grouped by state management.
- [structured-logging-standard](structured-logging-standard/) — Contributor material grouped by structured logging standard.
- [testing-verification](testing-verification/) — Contributor material grouped by testing verification.
- [verification](verification/) — Contributor material grouped by verification.

## Public, research and historical material

- [Public documentation](public/index.md) — Shipped operator and agent reference.
- [Teaching model](teaching/README.md) — Yokepedia source and teaching upkeep.
- [Archive](archive/) — Dated research and decisions, including [installation archetypes](archive/install-onboard-archetypes.md).

The Cursor assessment remains in the internal tree because the harness capability renderer consumes it. Performance diagnostics remains because the runtime teaching model cites its implementation evidence; its public operator guide lives in [public operations](public/operations/performance-diagnostics.md).

## Publish source documentation

After changing public pages, regenerate navigation, validate the corpus, and sync its installed and packaged copies. The [verification recipe](public/documentation/verification.md) owns the commands and publication checks.
