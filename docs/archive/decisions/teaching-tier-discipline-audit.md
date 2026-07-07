# Teaching-tier discipline + structural backstop

## Context

Yoke's teaching surfaces drift independently from the canonical schema
and CLI shapes when prose restates structural truth instead of citing it.
Two evidence runs (2026-05-14 and 2026-05-15) showed multiple agent
failures rooted in tier-discipline drift: skill prose teaching wrong
column names, CLI invocations with drifted flags, packet bullets missing
columns the workflow assumed, and prose linking the wrong direction
along the disclosure graph. Reactive packet-hotfix commits — the
`hotfix.*packet.*column` and `schema.*cheat.*sheet` patterns — became
the recurring repair shape.

## Decision

Encode the tiering as a closed enum with one canonical truth source per
fact class, and install a structural Doctor backstop that catches drift
at doctor time rather than waiting for the next agent failure.

### Seven teaching tiers

| Tier | Surface                                                           | Role                                                            |
|---:|-------------------------------------------------------------------|------------------------------------------------------------------|
| 0    | `AGENTS.md`, `runtime/harness/claude/rules/session.md`, `docs/prompt-philosophy.md` | Substrate disciplines, auto-loaded into every session prompt.    |
| 1    | Rendered `schema_api_context` packets (in-memory)                 | Canonical structural truth: tables, columns, CLI shapes, enums. |
| 2    | `docs/OVERVIEW.md`, `docs/lifecycle.md`, `docs/commands.md`, etc. | Orientation docs, read on demand.                                |
| 3    | `docs/function-inventory.md`, `docs/event-catalog.md`, `docs/db-reference.md`, `docs/db-reference/*.md`, `docs/state-management.md`, `docs/charge-frontier.md` | Reference catalogs every cross-reference points at.              |
| 4    | `runtime/agents/*.md`                                             | Canonical agent bodies; harness adapters derive from these.      |
| 5    | `.agents/skills/yoke/*/SKILL.md`                                | Skill prose, the workflow teaching surface.                      |
| 6    | `.agents/skills/yoke/*/<subdoc>.md`                             | Per-skill subdocs cited via progressive disclosure.              |

Tier 1 is the structural truth source. Tiers 0/2/4/5 cite toward Tier 1
and Tier 3 via sanctioned cross-reference prefixes; they never restate
schema, CLI, or enum facts inline.

### Structural backstop: five Doctor HCs

| HC slug                              | Catches                                                                                                              |
|--------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `HC-tier-schema-bleed`               | Tier 0/2/4/5 surfaces restating Tier 1 column facts (direct table.column or JSON nested field accessed as top-level). |
| `HC-tier-cli-shape-bleed`            | Drifted CLI flags / subcommands compared to live `--help`, bare-doctor invocations, stale subcommand help.            |
| `HC-packet-tier-completeness`        | Role packet missing a column referenced by a skill prose surface; main_agent envelope missing required fields.        |
| `HC-progressive-disclosure-direction`| Backward tier citations (e.g. Tier 0 linking a Tier 5 skill) and vague denials without a concrete registered function id. |
| `HC-tier-module-path-resolution`     | Confabulated `runtime.api.*` dotted module paths that `importlib.util.find_spec` cannot resolve.                      |

All five HCs run WARN in v0; findings are truncated to a per-HC budget.
Iteration is scoped via `iter_tier_paths` so the same tiering applies
across every HC; archive paths (`docs/archive/`) are exempt by default.

### Canonical cross-reference form

Lines that legitimately reach Tier 1 facts from Tier 0/2/4/5 open with:

- `see your \`` (e.g. `see your \`items\` packet stanza`),
- `see the \`` (e.g. `see the \`work_claims\` packet stanza`).

Anything matching this prefix is exempted from `HC-tier-schema-bleed`.
The allow-list lives at one canonical Python constant
(`runtime.api.engines.doctor_registry_tier_discipline.CROSS_REFERENCE_PREFIXES`)
so additions land in one place.

## Rationale

- **One truth per fact class.** Tier 1 is the only surface allowed to
  restate column lists, CLI shapes, and enum values. Every other tier
  cites toward Tier 1 rather than duplicating it. Drift cannot accrue
  because there is only one place to update.
- **Structural backstop > prose discipline.** Prose-only guidance has
  failed historically; the five HCs make drift visible at doctor time
  before the next agent dispatch consumes it.
- **WARN, not FAIL, in v0.** The bleed corpus is non-empty at landing
  time; the residue is captured in
  `runtime.api.engines.test_doctor_tier_discipline_integration.BASELINE_KNOWN_RESIDUE`
  and drained in a follow-up refinement ticket.
- **Sanctioned cross-references are narrow.** The packet-stanza-led
  form keeps the allow-list precise; unrelated prose does not silently
  exempt itself from bleed scanning.

## Removals (obsoleted content)

Reactive packet-hotfix commits matching the `hotfix.*packet.*column` or
`schema.*cheat.*sheet` patterns are no longer needed after this epic
merges; the five new HCs catch the regressing classes at doctor time.

Pointer back to authoring: see YOK-1700 for the epic plan and per-task
breakdown that landed this backstop.
