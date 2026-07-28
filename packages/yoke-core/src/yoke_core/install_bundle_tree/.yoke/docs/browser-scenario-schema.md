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
override it.

```json
{
  "base_url": "https://example.test",
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
`packages/yoke-harness/src/yoke_harness/browser_runtime/src/step-executor.js`.
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

## Assertion checks

| Check | Additional field | Meaning |
|---|---|---|
| `visible` | none | Target is visible. |
| `hidden` | none | Target is hidden. |
| `text_contains` | `expected` | Target text contains the expected string. |
| `text_equals` | `expected` | Trimmed target text equals the expected string. |
| `count_gte` | `min_count` | At least the requested number of targets exist. |
| `count_eq` | `expected` | Exactly the requested number of targets exist. |

The executor rejects aliases such as `url` for `route`, `selector` for
`target`, and `wait` for `delay` or `wait_for`.

## Authoring

Prefer a project-owned QA plan when the same Browser behavior should run for
more than one item:

```bash
yoke qa item-plan attach \
  --item YOK-N \
  --project <project> \
  --plan-id <plan-id> \
  --transition reviewing-implementation
```

For a one-off check, add an explicit method-backed requirement:

```bash
yoke qa requirement add \
  --item YOK-N \
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
through the shared case executor:

```bash
yoke qa plan materialize \
  --item YOK-N \
  --transition reviewing-implementation \
  --json

yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url <environment-url> \
  --expected-branch <branch> \
  --expected-sha <commit>
```

`browser-check` produces an automatic verdict from its assertions.
`browser-inspection` captures evidence and returns an inconclusive/review
outcome until a reviewer resolves it.

The executor writes the run and evidence on the materialized Browser
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

Read captured evidence with:

```bash
yoke qa artifact read \
  --requirement-id <requirement-id> \
  --artifact-id <artifact-id>
```

The transition remains blocked until every blocking, materialized or explicit
requirement has passed or been waived. Capture success alone is not a visual
quality verdict: inspection checks both visible defects and consistency with
the expected outcome.
