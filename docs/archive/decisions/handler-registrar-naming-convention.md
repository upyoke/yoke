# Handler registrar naming convention

## Decision

Yoke function-handler registrar wrappers under `runtime/api/domain/handlers/`
follow a **domain-keyed** naming convention:

```
_register_<domain>.py
```

The filename names the handler concern the wrapper registers (for example
`_register_claims.py` registers `claims.*` handlers, `_register_qa_reads.py`
registers `qa.*` plus reads/checks/renders). Earlier wrappers were named with
an ordinal suffix that recorded the task number inside whichever ticket
introduced the registrar (for example `_register_task3.py`, `_register_task9.py`).
The ordinal scheme is retired.

## Why ordinals were retired

The `_register_task<N>.py` shape made the registrar filename a shared mutex
on a single integer. Every new handler-batch ticket had to pick the next
available ordinal as its file path-claim, regardless of which domain its
handlers actually served. The system observed real coordination cost from
the scheme:

- New handler tickets raced for the next-integer filename even when their
  handler concerns were disjoint.
- A planned path-claim for `_register_task9.py` went stale the moment a
  different ticket landed first under the same ordinal.
- The `_PER_TASK_REGISTRARS` tuple name and the wrapper docstrings taught
  agents to think of each registrar as a "task" in a sequence rather than
  as a domain.

Renaming to `_register_<domain>.py` makes the file-path coordination
domain-keyed: the ticket adding `harness_messages.*` handlers picks
`_register_harness_messages.py` deterministically, the ticket adding
`scratch.*` handlers picks `_register_scratch.py` deterministically, and
no shared "next ordinal" slot exists.

## Going-forward rule

- New handler registrars MUST be named `_register_<domain>.py` where
  `<domain>` is a short, lowercase, underscore-separated phrase describing
  the handler concern.
- The `__init_register__.py` module imports and lists each registrar by
  its domain name in `_DOMAIN_REGISTRARS`. The explicit tuple stays
  explicit — no glob discovery.
- The thin-wrapper module is the only rename target. The handler-bearing
  sibling modules (`items_progress_log.py`, `claims_work.py`, `qa.py`,
  etc.) already carry domain names and are NOT subject to this convention.
- The `register(registry)` function signature on every wrapper is
  unchanged; this convention is module-name-only.

## Rename mapping applied at retirement

| Prior file               | Domain-keyed file                          |
|---                       |---                                         |
| `_register_task3.py`     | `_register_items_structured.py`            |
| `_register_task4.py`     | `_register_epic_tasks.py`                  |
| `_register_task5.py`     | `_register_items_scalar_lifecycle.py`      |
| `_register_task6.py`     | `_register_claims.py`                      |
| `_register_task7.py`     | `_register_qa_reads.py`                    |
| `_register_task8.py`     | `_register_ouroboros_recipe_events.py`     |
| `_register_task9.py`     | `_register_github_actions.py`              |

The `_PER_TASK_REGISTRARS` tuple in `__init_register__.py` was renamed to
`_DOMAIN_REGISTRARS` at the same time.
