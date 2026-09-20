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
about.

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

## Action reference

| Action | Required fields | Purpose |
|---|---|---|
| `navigate` | `route` | Navigate to a relative or absolute URL. |
| `click` | `target` | Click an element. |
| `type` | `target`, `value` | Type into an input. |
| `fill_form` | `fields` | Fill several target/value pairs. |
| `assert` | `target`, `check` | Evaluate an observable condition. |
| `screenshot` | `capture: true` | Save screenshot evidence. |
| `wait_for` | `target` | Wait for a visible element. |
| `delay` | optional `duration` | Wait a number of milliseconds. |
| `scroll` | optional `target`, `x`, `y` | Scroll to an element or offset. |
| `hover` | `target` | Hover over an element. |
| `select` | `target`, `value` | Choose a select option. |

Shared optional fields include `timeout_ms`, `source_ac`, and `refined`.
Authored plan cases should use verified selectors and set `refined: true` when
they include that field.

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

| Check | Additional field | Meaning |
|---|---|---|
| `visible` | none | Target is visible. |
| `hidden` | none | Target is hidden. |
| `text_contains` | `expected` | Target text contains the expected string. |
| `text_equals` | `expected` | Trimmed target text equals the expected string. |
| `count_gte` | `min_count` | At least the requested number of targets exist. |
| `count_eq` | `expected` | Exactly the requested number of targets exist. |

The runner rejects aliases such as `url` for `route`, `selector` for
`target`, and `wait` for `delay` or `wait_for`.

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

The method validator rejects missing steps, empty actions, and an empty
`base_url`.

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
When an inspection flow needs the low-level completion surface, it uses:

```bash
yoke qa run complete \
  --requirement-id <requirement-id> \
  --run-id <run-id> \
  --verdict pass
```

Review resolves that same Browser requirement to pass, fail, or waived. There
is no screenshot-to-AC bridge; the Browser case itself is the blocking proof.

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

The transition remains blocked until every blocking, materialized or explicit
requirement has passed or been waived. Capture success alone is not a visual
quality verdict: inspection checks both visible defects and consistency with
the expected outcome.
