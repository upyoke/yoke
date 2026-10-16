# Browser targets and methods

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Browser targets
<!-- /yoke:breadcrumbs -->

Choose where a Browser case runs, configure its immutable method and viewport, and interpret capture and review outcomes.

## Browser Methods

browser-check executes assertions and automatic verdict; browser-inspection
captures evidence for review. undetermined halts for owner/operator review.
An unexecuted precondition failure records blocked_on_precondition, fails its
scheduler, and creates no human work. Each requirement snapshots method_config;
routes/assertions/waits/screenshots belong there, not in qa_kind.

Correct an item config with qa.requirement.update --field method_config. A
deployment row freezes after pass/fail and refuses frozen_requirement_immutable
with supersession recovery. Item correction reconciles active admitted copies
(source-key/direct or matching plan/case/member/baseline/environment): unjudged
copies update atomically; answered/live-frozen copies refuse admitted_copy_in_flight
before either write. Terminal-run copies remain acceptance history. Already
waived/superseded copies are settled and cannot block correction.
A scope change (target_env, qa_phase, workflow_transition_id, blocking_mode)
or rebind-target that would break a replacement link refuses
replacement_link_scope_changed before writing; see
[requirement state model](requirement-state.md#links-that-stop-answering-for-their-obligation).

Copies execute their admitted definitions despite source drift. source_currency
diagnoses correction/refresh/new admission; drift alone never invalidates frozen
proof. At run start, raw_result records executed config and target digest,
retained through completion/review. A prior green proves neither later script
nor later target. Approval fails closed for executable captures lacking config.
In-place correction sets a persistent revision marker, even through empty config;
unstamped historic greens then fail. Plan currency compares executable config
without that marker; target_env correction stores the snapshot and acceptance
compares its start-bound digest.

Protected merge-queue CI receipts remain current for unchanged landing/config/
target even when old runners lacked start snapshots. Conflicting snapshots,
different landing or later failed/pending actual attempt still block. Matching
accepted admitted copies answer post-deploy sources for delivered candidate,
stage/member/environment through source-key or plan-case identity; no extra
source run/manual supersession. Failed/pending/mismatched copies still hold.

```json
{
  "method_id": "browser-check",
  "instructions": "Open the dashboard and verify its ready state.",
  "expected_outcome": "The dashboard is visible and ready.",
  "method_config": {
    "color_scheme": "light",
    "steps": [
      {"action": "navigate", "route": "/dashboard"},
      {"action": "assert", "target": "[data-ready=true]", "check": "visible"},
      {"action": "screenshot", "capture": true}
    ]
  }
}
```

Owned pages may declare light/dark. Runs/captures record requested and observed
media preference; missing/mismatched observation fails. Omission keeps ordinary
preference; use separate cases for both, then judge product appearance.
See [method configuration](browser-targets.md#method-configuration).

```text
yoke qa case run --requirement-id {REQUIREMENT_ID} --base-url {ENVIRONMENT_URL} --expected-branch {BRANCH} --expected-sha {COMMIT}
```

Deployment cases derive their own project's delivered commit: verified hosted
promotion attempt (including no-op), otherwise last release output then bound
commit. No supplied identity flags are needed. Missing/mismatched hosted
promotion, no delivered commit, conflicting supplied commit or unprovable served
environment refuses by name. Browser setup/status/screenshot/step are substrate
utilities; diagnostic captures create no parallel verdict. Use
[browser sign-in identities](browser-identities.md).

## Where a Browser case runs

A Browser case runs where the change becomes visible, against a server whose
own `/served-build` reports the commit the capture shows (see
[Proving which candidate the evidence shows](browser-scenarios.md#proving-which-candidate-the-evidence-shows)).
Every surface that authors a Browser case chooses its phase here:

| Where the change becomes visible | The case to author |
|---|---|
| A deployed environment | A `post_deploy` case with `--target-env ENV`, bound to the release stage. Target production; a plan case names stage only with a `stage_reason` ([case environment obligations](standalone-plans.md#case-environment-obligations)). The deployed server's own `/served-build` proves the commit. |
| Also a server the project runs from its unmerged candidate, reporting that commit at `/served-build` | A pre-merge `verification` case against that server is also available, bound to the review stage. |
| Nowhere — a prototype, design document, or other change no server serves | No Browser case. Select the `approval_on_done` posture (`--approval-on-done` at file time, or `yoke workflows item-posture amend PREFIX-N --key approval_on_done --value true --reason "..."`) so the operator signs off before the item closes. |

## Method configuration

`method_config` must be a JSON object with a non-empty `steps` array. An
optional `base_url` may provide the default target; the execution command can
override it. An optional `viewport` states the width and height the case is
about. A case that changes external state may declare `cleanup_steps`, a
sequence of one to five ordinary Browser steps to run after a failed required
step. For example, a dedicated actor round trip can include
`"cleanup_steps": [{"action": "click", "target": "#disable-actor"}]`.
Choose steps that restore a safe state from the page left by a failure.

Optional `browser_identity` names the project identity whose signed-in profile
the case runs as (default `default`), declared in the project's
`browser-control` capability settings; an identity never signed in on the
running host gets a clean context and a signed-out capture names the
`yoke browser authorize --identity NAME` command. A run whose cases name several identities starts
one daemon per identity, and the run's `sign_in` evidence names the identity.
See [browser sign-in identities](browser-identities.md).

Optional `color_scheme` is exactly `"light"` or `"dark"`; omit it for the
ordinary browser preference. It applies before navigation to this case's owned
page only, stays fixed across navigation/reload/steps, and never changes the
profile, OS, another page, or a following case. Use separate cases for both modes.
A resumed page must declare the same setting; otherwise close it and restart.
The daemon observes actual `prefers-color-scheme` before and after steps. Run and
screenshot metadata carry `color_scheme: {requested, observed}`. Invalid values,
emulation errors, missing observations and mismatches fail explicitly; repair
the named boundary and rerun. Older daemons missing observations cannot credit
a declared mode. Media preference proves browser input; assertions and visual
review still judge whether the application honors it. It creates no visual pass.

```json
{
  "base_url": "https://example.test",
  "viewport": {"width": 1440, "height": 900},
  "color_scheme": "dark",
  "steps": [
    {
      "action": "navigate",
      "route": "/login"
    },
    {
      "action": "assert",
      "target": "[data-testid='login-form']",
      "check": "visible"
    },
    {
      "action": "screenshot",
      "capture": true,
      "fullPage": true
    }
  ]
}
```

The step vocabulary matches
the browser step runner implementation.
There is no translation layer.

Required steps run in order until the first failure. The runner then records
that failure, takes one diagnostic screenshot from the owned page when it is
available, and skips subsequent required steps. It runs `cleanup_steps` after
the screenshot, even when cleanup follows a failed navigate, wait, assertion,
or interaction. Cleanup stops on its own first failure. The run retains the
original failed verdict and records any screenshot or cleanup failure beside
the original reason. Inspect `qa_run.raw_result.errors` and linked artifacts;
repair the named failure and rerun the case after restoring external state.

## Viewport

Declare the size a case is about, in one of two places:

- `method_config.viewport` — the size the whole case runs at. Write it
  whenever the case is about a particular width: a desktop layout, a sidebar
  that collapses, a table that reflows.
- `step.viewport` — the size one step and the steps after it run at, for a
  case that walks down the widths. Responsive behavior is only provable by
  resizing the real viewport, so a step that is about a phone says so.

```json
{"action": "screenshot", "capture": true, "viewport": {"width": 375, "height": 812}}
```

A case that declares neither runs at 1440x900. That default is stated, not
inherited: the runner opens a page for each case and sizes it before anything
loads, so no size, route, or signed-in screen carries over from the case
before it. Each capture records the viewport and url the page reported when
it was taken, beside the route the case navigated to.

## Related

- [Browser scenarios](browser-scenarios.md)
- [Browser evidence](browser-evidence.md)
