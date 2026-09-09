# The title limit is one project-aware policy, not a number each surface keeps

## Context

The item and epic-task title limit was the literal `100`, written
independently into a domain constant, an epic-task guard, two request
models, a browser input, a doctor scan's SQL and its messages, a CLI help
string, an API reference table, several agent bodies, and a handful of
skills. Nothing tied those copies together, so changing the limit meant
finding every one of them and no surface could ever differ from another
on purpose.

Three further defects came with the duplication:

1. The epic-task metadata write path accepted a title of any length,
   because only the upsert carried a check. Amending metadata bypassed
   the limit the create path enforced.
2. Request models declared `max_length=100` in Pydantic, ahead of any
   project resolution. A project-dependent limit could never be enforced
   from behind a fixed request-model declaration — the model would refuse
   first, with its own competing number.
3. Two agent bodies and a docs table told readers "the DB rejects titles
   >100 chars". The `title` columns are unbounded `text` with no CHECK
   and no trigger; the refusal has always come from application code.

## Decision

One default constant and one resolver live in the shared contracts layer
(`yoke_contracts.title_policy`):

- `DEFAULT_TITLE_MAX_LENGTH` — the value every project resolves to.
- `title_max_length(project)` — the effective limit for a project, named
  by slug or id.
- `title_length_error(title, project=..., subject=...)` — the shared
  refusal, so the count and the number in the message always agree and
  character counting has one definition.

Every enforcing surface resolves through that resolver against the right
project: creation against the selected project, item title edits against
the item's owning project, epic tasks against their parent item's project
(`yoke_core.domain.title_policy` answers "which project owns this row"),
and the doctor scan against each row's own project. Request models declare
no length, so validation happens after the project is known. The browser
form reads the effective limit from the project-scoped
`workflows.definition.get` response and refuses to render rather than
silently capping at zero when the server serves none.

The effective limit remains 100 for every project. The resolver's project
argument is a seam, not a feature: it exists so a future override changes
one function instead of a dozen call sites.

## Consequences

- Changing the default changes every enforcing and teaching surface at
  once. `runtime/api/test_title_policy.py` proves this by moving the
  default to a value nothing else carries and asserting each surface
  follows; a surface that kept its own number fails there.
- Teaching surfaces name the policy rather than a number, and point at
  `workflows.definition.get` (`title_max_length`) for the live value.
- Doctor keeps WARN severity and now names the limit it judged against,
  so a report is readable without knowing the policy.

## What a real per-project override still needs

This change deliberately builds none of the following. Each is required
before `title_max_length(project)` can return anything but the default:

- **Storage and validation.** Somewhere to put a per-project limit
  (`project_capabilities` or a project settings key), with its own
  validation — a lower bound that keeps titles usable, and an upper bound
  the storage can hold.
- **Resolution precedence.** A stated order for project override, org
  default, and shipped default, and one answer for an unreadable or
  malformed stored value: refuse, or fall back and say so.
- **Client refresh.** The browser reads the limit once per project-scoped
  load. An override that can change while a form is open needs the form
  to re-read it, or an explicit statement that it does not.
- **Project moves.** An item moved to a project with a shorter limit
  carries a title that project would refuse. Decide whether the move is
  blocked, the title is flagged, or existing rows are grandfathered — the
  doctor check already reports them either way.
- **Lowering a limit.** Same question for an in-place lowering, which can
  make a large number of stored titles non-conforming at once. Existing
  titles are never rewritten or truncated by this change, and nothing
  here should start doing so silently.
