# Browser request interception

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Browser request interception
<!-- /yoke:breadcrumbs -->

Use the existing browser step surface to prove that a page remains usable
while a named function call is pending or fails. This changes browser traffic
only; it creates no server-side data and grants no permission to fault a
production service. Use it only on the case's authorized target.

```json
{"action":"request_interception","function_id":"qa.activity.read","mode":"hold"}
```

Install the rule before navigating to the view that starts the request.
It matches POST requests with a JSON body's exact `function` field, only on
this owned page and only at the `--base-url` origin. Other functions, origins
and pages continue normally. Service-worker-owned traffic is not covered by
Playwright page routing; use a fixture without a service worker for this proof.

Choose `mode`:

- `hold` keeps matching requests pending until a later step changes the rule.
- `reject` aborts held and future matching requests as a network failure.
- `status` observes the existing rule without changing it.
- `release` forwards held requests, removes the rule and restores normal traffic.

Each result includes `interception` with `function_id`, `mode`, cumulative
`matched`, `rejected` and `released` counts, and the current `pending` count.
Use `status` to prove the intended request actually matched before asserting
cards remain visible or taking a screenshot. Installing a rule alone proves
nothing. Request bodies, headers and cookies are never copied into this result.

```json
{"action":"request_interception","function_id":"qa.activity.read","mode":"status"}
{"action":"assert","target":".shipping-run","check":"count_gte","min_count":12}
{"action":"request_interception","function_id":"qa.activity.read","mode":"reject"}
{"action":"screenshot","capture":true,"label":"cards-during-auxiliary-failure"}
{"action":"request_interception","function_id":"qa.activity.read","mode":"release"}
```

Use the application's actual card selector. Repeat for each required function,
such as `deployment_flows.list`. Changing an existing rule from reject to hold
affects new requests; it cannot replay a request already rejected. Navigate
again to trigger new traffic. Closing the owned page discards its rules and
aborts its pending traffic. A fresh page inherits none of them.

An unknown rule refuses as `browser_interception_missing`; install hold or
reject on that page first. A changed origin refuses as
`browser_interception_origin_mismatch`; release using the original base URL
before installing another rule. A non-HTTP base URL refuses as
`browser_interception_origin_required`; use the actual HTTP or HTTPS target.

## Mission cache isolation

Set `YOKE_MACHINE_HOME` to the mission's scratch machine home before setup,
authorization and steps. The shared resolver puts Chromium at
`$YOKE_MACHINE_HOME/playwright-cache/yoke`, beside the isolated runtime and
profiles. An inherited `PLAYWRIGHT_BROWSERS_PATH` cannot redirect installation.
All clients use this same resolver.
Isolated setup may download Node, npm dependencies and Chromium into that
scratch home, but never installs OS libraries or AppArmor profiles. A missing
host prerequisite refuses as `browser_isolated_system_setup_required`; use
a QA host prepared with those prerequisites and retry in the same scratch home.

An explicit machine home pointing into ordinary `~/.yoke`, or a cache symlink
escaping the selected machine home, refuses before setup writes as
`browser_cache_not_isolated`. Select the mission scratch directory and repair
the escaping symlink, then retry `yoke qa browser setup`. Without an override,
the ordinary cache remains `~/.yoke/playwright-cache/yoke`.
