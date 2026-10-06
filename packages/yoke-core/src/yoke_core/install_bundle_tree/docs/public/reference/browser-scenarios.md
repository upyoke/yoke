# Browser Case Configuration

Browser verification is a QA method contract. Reusable cases live in
`qa_plan_cases`; one-off cases live in `qa_requirements`. Both carry the same
`method_id`, instructions, expected outcome, and `method_config`.

Use:

- `browser-check` when declared assertions can decide pass or fail.
- `browser-inspection` when screenshot evidence needs human judgment.

Items do not carry a second browser-testability classification. A Browser case
exists only when a plan attachment or explicit requirement declares it.

## Method configuration

`method_config` must be a JSON object with a non-empty `steps` array. An
optional `base_url` may provide the default target; the execution command can
override it. An optional `viewport` states the width and height the case is
about. A case that changes external state may declare `cleanup_steps`, a
sequence of one to five ordinary Browser steps to run after a failed required
step. For example, a dedicated actor round trip can include
`"cleanup_steps": [{"action": "click", "target": "#disable-actor"}]`.
Choose steps that restore a safe state from the page left by a failure.

```json
{
  "base_url": "https://example.test",
  "viewport": {"width": 1440, "height": 900},
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

## Action reference

| Action | Required fields | Purpose |
|---|---|---|
| `navigate` | `route` | Navigate to a relative or absolute URL. |
| `click` | `target` | Click an element. |
| `type` | `target`, `value` | Type into an input. |
| `fill_form` | `fields` | Fill several target/value pairs. |
| `assert` | `target`, `check` | Evaluate an observable condition. |
| `screenshot` | `capture: true` | Save screenshot evidence. Optional `label` names the capture, `target` frames it on one element, `fullPage` captures the whole document. |
| `wait_for` | `target` | Wait for a visible element. |
| `ready` | `target`, `text`, or both | Wait for a loading placeholder to go away. |
| `delay` | optional `duration` or `duration_ms` | Wait a number of milliseconds. |
| `scroll` | optional `target`, `x`, `y` | Scroll to an element or offset. |
| `hover` | `target` | Hover over an element. |
| `select` | `target`, `value` | Choose a select option. |

Shared optional fields include `timeout_ms`, `source_ac`, `refined`, and
`viewport`. `timeout_ms` is the wait budget every waiting action and
assertion honours. A step that sets a key its action does not define is
refused; the refusal names the unrecognised key and the keys that action
defines. Authored plan cases should use verified selectors and set
`refined: true` when they include that field.

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

## Assertion checks

| Check | Additional field | Waits | Meaning |
|---|---|---|---|
| `visible` | none | yes | Target is visible. |
| `hidden` | none | yes | Target is hidden. |
| `text_contains` | `expected` | yes | Target text contains the expected string. |
| `text_equals` | `expected` | yes | Trimmed target text equals the expected string. |
| `count_gte` | `min_count` | yes | At least the requested number of targets exist. |
| `count_eq` | `expected` | yes | Exactly the requested number of targets exist. |

Every assertion honours `timeout_ms` (default 5000ms): `count_gte` and
`count_eq` poll until the count holds or that budget expires. `wait_for`
waits for a visible target. `delay` waits `duration` / `duration_ms`; it
does not take a destination.

### Presence questions accept a selector matching many elements

`wait_for`, `visible`, and `hidden` ask whether the screen shows something,
so they resolve the first match. A selector naming a repeated component —
`.shipping-run-card` on a page holding a dozen of them — is a correct way to
ask "did the cards render", and it is honoured as "at least one".

The checks that read a value stay strict: `text_contains`, `text_equals`,
`count_gte`, and `count_eq` refuse a selector matching more than one element
rather than reporting one element's text as the page's answer. Narrow the
target, or use a count check when the number is the point.

### Waiting for a screen to settle

`wait_for` waits for something to appear. `ready` is the opposite question —
waiting for the placeholder to leave — and it is what keeps a capture or an
assertion off a skeleton that has already rendered its container. State the
placeholder as a selector, as the text it shows, or both; every one named
must be gone before the step passes.

```json
{"action": "ready", "target": ".skeleton", "text": "Loading"}
```

A `ready` step naming neither is refused: it would pass instantly and read
as proof that the page had settled.

### Framing a capture

`fullPage` grows with the document, so it is the right framing for a page
that scrolls the document itself. An app that scrolls an inner container
leaves the document at viewport height, and an element below the fold does
not appear at all — a capture that looks complete and is not.

Name the element instead, and the capture is scrolled into view and framed on
its own box:

```json
{"action": "screenshot", "capture": true, "target": "#run-panel", "label": "run panel"}
```

The box is what the element shows, not its scrollable content: a capture
cannot photograph pixels the page never painted. A case covering a long
inner-scrolling list pairs `scroll` with a capture per screenful.

The runner rejects aliases such as `url` for `route`, `selector` for
`target`, and `wait` for `delay` or `wait_for`. A navigate step that sets
`target` instead of `route` is refused rather than falling through to the
base URL.

### Absence assertions and what they observed

`hidden`, `count_eq` of 0, and `count_gte` of 0 are all satisfied by a page
holding no matching element at all — Playwright reports a detached locator as
hidden, and a locator matching nothing counts zero. The runner therefore reads
the match count where it resolves the assertion and, when an absence-shaped
check passed against zero elements, reports it as `vacuous_absence` on the
step result. Every other check fails against a zero-match locator, so none of
them can pass this way.

Asserting absence is often exactly right, so nothing is refused at authoring
time and a `hidden` assertion against a present element means precisely what
it always did. The rule is about the case: if *no* assertion in a case ever
matched an element, the case never saw the page and proved nothing, so a
`browser-check` in that state fails with `assertion_vacuous_absence` instead
of passing, naming the commands that correct and re-run it. A case that also
asserts something the page does show has observed a rendered screen, so the
absence it asserts beside it is a real finding and stays a pass.

Either way the zero-match guards are recorded — on the run's `raw_result` as
`vacuous_absences`, and in the metadata of every capture taken after them, so
a reviewer judging a bundle can see that the guard meant to settle a screen
matched no element on it.

## Authoring

Prefer a project-owned QA plan when the same Browser behavior should run for
more than one item:

```bash
yoke qa item-plan attach \
  --item PREFIX-N \
  --project <project> \
  --plan-id <plan-id> \
  --transition reviewing-implementation
```

For a one-off check, add an explicit method-backed requirement:

```bash
yoke qa requirement add \
  --item PREFIX-N \
  --method-id browser-check \
  --qa-phase verification \
  --workflow-transition reviewed-implementation \
  --instructions "Open /login and inspect the form" \
  --expected-outcome "The login form is visible and usable" \
  --method-config '{"steps":[{"action":"navigate","route":"/login"},{"action":"assert","target":"[data-testid=login-form]","check":"visible"},{"action":"screenshot","capture":true}]}'
```

The method validator rejects missing steps, empty actions, an empty
`base_url`, and a step key the action does not define.

## Execution

Materialize plan cases at their declared transition, then run each requirement
through the shared case runner:

```bash
yoke qa plan materialize \
  --item PREFIX-N \
  --transition reviewing-implementation \
  --json

yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url <environment-url> \
  --expected-branch <branch> \
  --expected-sha <commit>
```

`browser-check` produces an automatic verdict from its assertions.
`browser-inspection` captures linked evidence and can return an undetermined
outcome that halts the item until a project owner/operator resolves its review.
Without linked evidence, execution fails and no human review is requested.

The runner writes the run and evidence on the materialized Browser
requirement. Do not create a second requirement or run to mirror that result.

### Reviewing a capture

One command records a `browser-inspection` review:

```bash
yoke qa run record-verdict \
  --requirement-id <requirement-id> \
  --performed-by agent \
  --verdict pass \
  --verdict-reason "what the screenshots showed"
```

It resolves the capture the review judged, in place — the capture stays the
requirement's latest run, keeping the commit its screenshots were taken
against — and writes the capture-to-review link the evidence gate requires.
Pass no `--raw-result`: the capture's payload already names that commit, and
replacing it is refused rather than discarding the only proof of which tree
the evidence shows.

`yoke qa run complete` settles a run's verdict and writes no review link, so
it does not satisfy a `browser-inspection` gate and is not the review command.
Review resolves that same Browser requirement to pass, fail, or waived. There
is no screenshot-to-AC bridge; the Browser case itself is the blocking proof.

### Proving which candidate the evidence shows

`--expected-branch` / `--expected-sha` are verified by reading `/served-build`
on the target the run was given (`--base-url`). A pre-merge candidate is
proved there, and production is not asked. A mismatch refuses as
`sha_mismatch`. A target that cannot answer refuses as
`identity_proof_unavailable` and records no run. The candidate review server
publishes that path to the run's own session, with no separate secret, the
same way a local or self-hosted server publishes it before sign-in. A static or third-party
preview publishes nothing there however current it is, so a pre-merge capture
needs a target running this project's own build from a committed checkout —
the same build that answers that path in its deployed environments. Commit
first: a checkout with uncommitted changes publishes `<sha>-dirty`, which
fails the match closed because it is not the committed contents it would be
certified as.

Visible dashboard tabs compare their loaded build with site-root `/served-build`
on focus, visibility return, and every minute. A changed build shows a persistent notice
with a Reload button; reload is manual to preserve unsaved drafts. Empty or
failed reads leave the page usable without a notice. Hosted dashboards under
`/orgs/<org>` also check the site root; the first successful read supplies the
baseline when the host packet has no build identity.

## Evidence and gates

Read captured evidence with the command the capture already reported under
`artifact_reads`:

```bash
yoke qa artifact read \
  --requirement-id <requirement-id> \
  --artifact-id <artifact-id>
```

It lands the bytes under this machine's temp root and reports that path as
`path`; open that, not the capture's own `artifacts` scratch paths. Add
`--output PATH` to choose the destination yourself.

A full-page capture of a long screen is one very tall image, and a viewer
that scales it to fit makes every label in it unreadable. Read the part being
judged instead:

```bash
yoke qa artifact read \
  --requirement-id <requirement-id> \
  --artifact-id <artifact-id> \
  --region 0,900,1440,600 \
  --scale 1.5
```

`--region x,y,w,h` is a pixel rectangle measured from the top-left of the
capture; `--scale` multiplies the rendered size and applies after the region,
so one panel can be enlarged to read its small text. The stored artifact is
never modified — a view is a way of reading evidence — and the response
reports the `artifact_view` it rendered (source size, region, scale, rendered
size), so a finding can name the region it was seen in. A region falling
outside the image, an unreadable scale, and a non-image artifact each refuse
by name and say where the recorded bytes landed.

Captures store their screenshots through the build serving the universe, so a
hosted reviewer sees the same images: from a `*-db-admin` connection the
evidence writes relay to its paired https connection (`prod-db-admin` →
`prod`). No review request is raised against a screenshot a hosted reviewer
cannot open. Evidence already recorded only on the capture machine is moved in
place from that machine with
`yoke qa artifact rehome --requirement-id <id> --artifact-id <id>`.

The transition remains blocked until every blocking, materialized or explicit
requirement has passed or been waived. Capture success alone is not a visual
quality verdict: inspection checks both visible defects and consistency with
the expected outcome.
