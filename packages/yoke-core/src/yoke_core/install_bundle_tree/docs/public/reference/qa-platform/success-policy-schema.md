# success_policy JSON Schema

The `success_policy` column on `qa_requirements` stores a JSON object defining what counts as success. Five policy types are supported. Downstream consumers (conduct, usher) implement policy evaluation; a centralized evaluation engine is deferred. Cross-link back from [qa-platform.md](../qa-platform.md) for the table schemas, gating semantics, and CLI surface that consume these policies.

## Type: deterministic

Simple pass/fail based on a concrete check.

```json
{"type": "deterministic", "criteria": "verdict_pass"}
```

```json
{"type": "deterministic", "check": "exit_code", "expected": 0}
```

```json
{"type": "deterministic", "check": "http_status", "expected": 200}
```

**Semantics:** A single QA run with a matching result satisfies the requirement. The `check` field names the metric; `expected` is the exact value that constitutes success. The shorthand `"criteria": "verdict_pass"` means `verdict == 'pass'`.

## Type: threshold

Numeric score must meet or exceed a threshold.

```json
{"type": "threshold", "metric": "score", "threshold": 3.5, "operator": "gte"}
```

**Fields:**
- `metric` -- which numeric field to evaluate (`score`, or a key in `raw_result` JSON)
- `threshold` -- the numeric boundary
- `operator` -- comparison operator: `gte` (>=), `gt` (>), `lte` (<=), `lt` (<), `eq` (==)

**Semantics:** A single QA run where the specified metric satisfies the threshold/operator passes the requirement.

## Type: statistical

Pass rate across multiple runs.

```json
{"type": "statistical", "min_runs": 10, "min_pass_rate": 0.7}
```

**Fields:**
- `min_runs` -- minimum number of runs required before the policy can be evaluated
- `min_pass_rate` -- fraction of runs that must have `verdict='pass'` (0.0 to 1.0)

**Semantics:** The requirement is satisfied when at least `min_runs` QA runs exist AND at least `min_pass_rate` fraction of them have `verdict='pass'`. Runs with `verdict='inconclusive'` are excluded from both the numerator and denominator. Runs with `verdict='error'` count as failures.

## Type: composite

Multiple sub-criteria that must all be met.

```json
{
 "type": "composite",
 "rules": [
 {"metric": "layout_score", "min": 4},
 {"check": "no_missing_elements"},
 {"metric": "color_match", "min_pct": 80}
 ]
}
```

**Fields:**
- `rules` -- array of sub-rule objects, each checked against the QA run's `raw_result` JSON

**Semantics:** All rules must pass for the overall requirement to be satisfied. Each rule is evaluated against the `raw_result` JSON of the QA run. A `metric` rule checks a numeric value; a `check` rule checks for the presence of a boolean key.

## Type: agent_judgment

Agent-judged assessment with confidence thresholds for non-deterministic QA.

```json
{
 "type": "agent_judgment",
 "confidence_pass": 0.8,
 "confidence_fail": 0.4,
 "min_runs": 3
}
```

**Fields:**
- `confidence_pass` -- confidence level at or above which a verdict of `pass` is accepted (0.0-1.0)
- `confidence_fail` -- confidence level at or below which a verdict of `fail` is accepted (0.0-1.0)
- `min_runs` -- minimum number of runs before the policy can be evaluated

**Semantics:** This is the critical policy type for LLM-judged visual QA. The Tester agent reads screenshots (Claude is multimodal) and judges against ACs, producing a `verdict` and `confidence` score on each run.

Decision logic:
1. If fewer than `min_runs` exist, the requirement is **inconclusive** (not yet evaluable).
2. If any run has `verdict='pass'` AND `confidence >= confidence_pass`, the requirement is **satisfied**.
3. If all runs have `verdict='fail'` AND `confidence >= (1 - confidence_fail)`, the requirement is **failed**.
4. Otherwise, the requirement is **inconclusive** -- more runs are needed or results are ambiguous.

The gap between `confidence_pass` and `confidence_fail` defines the "inconclusive zone" where results are neither clearly passing nor clearly failing.
