# Project-local health checks

Checks in this folder belong to **this project**. They run alongside the
engine's universal roster whenever doctor runs on a machine that holds this
checkout, and they report through the same sections of the Ouroboros Health
Report.

Most of what lives here are Yoke's own source-development invariants — agent
prompt and adapter drift, harness hook parity, skill and doc consistency,
teaching-tier discipline, code-doctrine scans. They used to ship in the
engine to every install, where they had nothing to inspect. The engine roster
that remains is what is true of *any* project Yoke manages.

## Discovery

Discovery is pytest-shaped: every `check_*.py` file here is imported, and
each `hc_*(conn, args, rec)` function it defines becomes a health check.
Anything else in the folder — helpers, fixtures, this README — is ignored.

* **Slug** comes from the function name: `hc_release_pin_freshness` →
  `HC-release-pin-freshness`.
* **Display name** comes from the first line of the docstring.
* **Applicability** comes from a module-level `APPLICABILITY`, or per
  function via an `applicability` attribute. A module may instead declare an
  explicit `PROJECT_HEALTH_CHECKS` list of `HealthCheck` rows for full
  control. That name is deliberately not `HEALTH_CHECKS`: a check that
  imports the engine's own roster to inspect it must not thereby declare all
  of it as this project's.

A module that fails to import is reported as a FAIL, not skipped — a check
that cannot load never runs, and silence would read as health.

## Verification audit

The merge-gating test suite imports every discovered `check_*.py` module and
executes every declared check against its disposable Postgres control plane.
It also asserts the source-checkout applicability that keeps these checks out
of runtimes where their project tree is unavailable.

The complete module-symbol audit covers all 48 check modules and 230
attribute references on imported modules. Ruff's undefined-name/import scan
found no additional issues; the attribute audit found and corrected the lone
invalid reference, `json_helper.loads` in the migration-ledger contract check.
The executable family test seeds that check's migration-model branch so its
function-local imports and symbol references are reached.

## Applicability

Declare what the check applies to so the runner can tell "passed" from "not
applicable". The axes are project scope, source-checkout dependence,
runtimes, and required project capabilities:

```python
from yoke_core.engines.doctor_applicability import (
    CheckApplicability, PROJECT_SCOPE_SELF,
)

APPLICABILITY = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF,
    requires_source_checkout=True,
)


def hc_example(conn, args, rec):
    """One-line display name."""
    rec.record("HC-example", "One-line display name", "PASS", "")
```

`rec.record(check_id, name, severity, detail)` takes `PASS`, `WARN`, or
`FAIL`. Leave `N/A` to the runner: it is the applicability model's answer,
not a check's.

## Where a check belongs

Engine, or here?

* **Engine** — the check states something true of *every* Yoke project:
  backlog integrity, lifecycle continuity, deployment-run consistency,
  claim hygiene.
* **Here** — the check states something true of *this* project: its own
  conventions, its own file layout, its own doctrine.

Hosted and custom checks are data-driven assertions over the control plane,
never arbitrary code in the engine. A project that needs code runs it from
its own folder, on its own machine, against its own checkout.
