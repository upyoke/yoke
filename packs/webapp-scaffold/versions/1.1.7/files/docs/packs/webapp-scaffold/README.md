# Webapp Scaffold Pack

A FastAPI, Next.js, and app-local SQLite starting point for a new web
application. It installs application code, tests, local configuration examples,
and a basic CI workflow; every installed file becomes ordinary project-owned
source.

## What this Pack installs

- A FastAPI service with cookie authentication, health routes, background-task
  helpers, tests, and boot-coupled SQLite migrations with membership and
  exact-module SHA256 identity plus exact rollback-serving-floor checks. Every
  apply requires an artifact version, executes one captured source image, and
  establishes a named, WAL-consistent SQLite restore point before pending work.
  Legacy rows require explicit, project-verified artifact evidence plus
  commit-bound manifest and state-invariant adoption. Receipt-first transitions,
  append-only receipts, and immutable membership guards block readiness when
  absent and can be repaired only by explicit adoption. The runner never infers
  legacy identity from current source.
- A Next.js application shell with login, dashboard, settings, shared UI
  components, Vitest support, and Playwright examples.
- A canonical application guidance reference, a roadmap starter, environment examples,
  ignore rules, and .github/workflows/ci.yml.

It does not install Docker, Pulumi, AWS, deployment, smoke, preview-environment,
host-maintenance, or runner-fleet code. Those are separate Packs so each
capability can be installed and updated independently.

## Install-time settings

The descriptor requires only values used by scaffold files:

| Setting | Purpose |
|---|---|
| project_name | Lowercase code and resource prefix |
| project_slug | Stable Yoke project slug |
| project_display_name | Human-readable application name |
| project_description | One-line application description |
| api_port | Local API port |
| web_port | Local web port |

Values come from the registered project's Yoke settings; secrets never enter
the Pack bundle or receipt.

## Install

Preview first:

    yoke packs get webapp-scaffold /path/to/project --project <project>

Review every created file and conflict, then apply:

    yoke packs get webapp-scaffold /path/to/project --project <project> --apply

The apply writes .yoke/packs.json. Commit the installed code and receipt
together after the project review.

## Co-owned guidance and ignores

Setup wires Yoke into a project; `/yoke onboard` chooses and installs the
application scaffold. This version contributes one reference to
[application.md](application.md) in root `AGENTS.md`, outside the existing
Yoke managed block. It supplies no `CLAUDE.md`, `CODEX.md` or `CURSOR.md`.
Use the supported harness configuration established by project installation;
an unsupported or ambiguous instruction-loading configuration must be repaired
there before resuming application work. Canonical instruction discovery is
documented by [Codex](https://developers.openai.com/codex/guides/agents-md/),
[Cursor](https://cursor.com/docs/rules) and
[Claude Code](https://code.claude.com/docs/en/memory).

Only root `AGENTS.md` and `.gitignore` accept explicit contributions. Their
immutable Pack sources contain only one complete block named for the Pack:
`<!-- BEGIN YOKE PACK webapp-scaffold -->` / matching `END` for Markdown;
`# BEGIN YOKE PACK webapp-scaffold` / matching `END` for ignores. These are
distinct from the project-install-owned Yoke block. All surrounding bytes and
the existing file mode stay project-owned. The receipt records the contribution
digest as its upstream baseline, rather than claiming the composed file.
Contribution targets cannot be relinked: restore their canonical root path
before an update; application files retain ordinary relink support.

Preview and apply use the same planner. Repeating `get` refuses with `use update`;
an unchanged `update` keeps exactly one contribution. Project-install refresh
rewrites its own block and preserves the contribution. New Pack versions merge
only the contribution against its recorded baseline, leaving surrounding
guidance and custom ignore rules intact. Ordinary application files still refuse
first-install collisions: reconcile or move the named file and preview again.

Missing, repeated, reversed or nested boundaries refuse before any writes.
Repair the named boundaries outside the Yoke block, preserving project content,
then preview again. `--accept-current` cannot bypass contribution conflicts.
If updating an old whole-file scaffold baseline, unchanged scaffold content is
retired through three-way merge before the contribution is inserted. Customized
old guidance can conflict: reconcile it into application docs, install the
exact incoming marked reference outside the Yoke block, and keep project notes
outside the Pack contribution, then retry. Removed legacy files are retained
as project-owned files; project installation owns the canonical-loading repair
for obsolete guidance duplicates. Prior immutable Pack versions never change.

## Instant representation and upgrades

Application code carries aware UTC datetimes; owned JSON and SQLite bindings use
fixed-six UTC RFC3339 strings or field-permitted null. The shared parser refuses
blank, date-only, naive, numeric, and unknown-offset inputs. Task duration and
retention use monotonic clocks. Session expiry is parsed before native comparison.

The appended canonical-instant migration validates all five application columns
before rebuilding the four scaffold tables in one guarded transaction. Boot
establishes the existing WAL-consistent restore point first. The entry records
the applying artifact's version as its serving floor through `next-release`;
older builds fail readiness. It recognizes only the prior scaffold UTC producers
and refuses custom tables, indexes, triggers, external views or foreign keys that
need a project-owned migration. Preserve the named restore point on refusal.

Historical migration membership and append-only adoption receipts retain their
exact clock bytes and guard schema. New evidence writes bind canonical clocks
explicitly. Prior published Pack versions and permanent history entries remain
unchanged; customized installations must rehearse their own merged migration.

## Intentional project-specific gaps

The scaffold is deliberately not a finished product. Before calling it
functional, the project must:

1. Replace sample copy, routes, data models, navigation, and visual styling.
2. Choose its real identity, authorization, persistence, migration, backup,
   secret, logging, telemetry, and incident models.
3. Decide whether app-local SQLite remains appropriate or adapt the application
   layer to another database.
4. Add domain behavior and tests.
5. Select and configure only the runtime and delivery Packs it actually needs.
6. Replace these generic notes with project-owned operating and recovery
   runbooks.

See customization.md for ownership and update guidance and development.md for
the installed development surface.

## Local development

    cd app
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python3 db/init_db.py
    pytest

    cd app/web
    npm install
    npm run dev

Copy .env.example to an ignored .env file and replace every example secret
before using the application outside local development.

## Add independent capabilities

Inspect the catalog and preview only the capabilities the project needs:

    yoke packs list --project <project>
    yoke packs get container-runtime /path/to/project --project <project>
    yoke packs get pulumi-foundation /path/to/project --project <project>
    yoke packs get production-deploy /path/to/project --project <project>

Each selected Pack carries its own dependencies and setup gaps. The scaffold
does not imply that all web applications need the same infrastructure.

## Update

    yoke packs update webapp-scaffold /path/to/project --project <project>

Yoke three-way-merges the new immutable Pack version with the project's current
customizations. Non-overlapping changes are previewed normally; overlapping
changes become explicit conflicts. Yoke does not police unrelated project
changes, automatically delete project files, or expect customized files to be
reported back to the Pack source.

After manually merging an overlapping change into a project-owned file,
acknowledge that exact reviewed path while previewing and then applying:

    yoke packs update webapp-scaffold /path/to/project --project <project> \
      --accept-current app/web/src/test/setup.ts
    yoke packs update webapp-scaffold /path/to/project --project <project> \
      --accept-current app/web/src/test/setup.ts --apply

Yoke preserves the current file and advances the Pack baseline only when the
named path is one of the update's current conflicts.

UTC conversion outside years 1 through 9999 refuses with `invalid_instant`; valid boundary instants retain all six fractional digits.
