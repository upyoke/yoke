# Webapp Scaffold Development Reference

## Installed backend

| Area | Main paths |
|---|---|
| FastAPI application | app/api/ |
| Authentication and request dependencies | app/api/auth.py, app/api/dependencies.py |
| Routers | app/api/routers/ |
| Background tasks and progress | app/api/tasks/ |
| SQLite schema and migrations | app/db/ |
| Shared application helpers | app/utils/ |
| Pytest coverage | app/tests/ |

## Installed frontend

| Area | Main paths |
|---|---|
| Next.js routes and layouts | app/web/src/app/ |
| Shared components | app/web/src/components/ |
| API and type helpers | app/web/src/lib/ |
| Client state | app/web/src/store/ |
| Unit-test support | app/web/src/test/ |
| Playwright examples | app/web/e2e/ |

## Local commands

Backend:

    cd app
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python3 db/init_db.py
    pytest
    uvicorn api.main:app --reload

Frontend:

    cd app/web
    npm install
    npm run dev
    npm run build

The exact commands should be recorded in the project's Yoke Project Structure
after the project chooses its package manager and test policy.

## CI

The Pack installs only .github/workflows/ci.yml. Review its runtime versions,
dependency caching, test commands, and branch triggers before relying on it.
Delivery workflows are intentionally outside this Pack.

## Adding application code

- Add API routers under app/api/routers/ and mount them in api/main.py.
- Add schema changes through migrations rather than editing production state.
- Add web routes under app/web/src/app/.
- Add reusable UI through the project's chosen component workflow.
- Keep domain-specific services, scheduled jobs, queues, and third-party
  integrations in the project; the scaffold cannot guess them.

## Migration contract

Migration entries under `app/db/migrations/` are permanent files named
`NNNN_slug.py`. Each exposes `apply(conn)` and may expose `invariants(conn)`;
mutation, invariants, the filename-stem membership row, the SHA256 of the
module's exact bytes, and its serving floor commit in one transaction. Sequence
numbers order entries but never decide whether one is pending, so a
lower-numbered entry merged later still runs.

An entry containing `DROP TABLE` or `DROP COLUMN` declares
`MINIMUM_SERVING_VERSION`, the oldest application version safe against the
result. Boot applies the pending membership set before serving. The public
health endpoint fails when history is pending, an old numeric ledger row cannot
be mapped to its permanent filename, an applied entry in this artifact lacks
content evidence, recorded content differs from the exact shipped bytes, a
shipped entry's recorded floor differs from its packaged declaration, a
ledger-ahead entry has no floor, or this build is below any recorded floor. A
non-NULL content mismatch is checked before backup, ledger mutation, or a
current-database return. Keep migration files forever.

Rows written before content identity carry a NULL `content_sha256` and report
`adoption_required`; boot never fills that field from whatever source happens
to be present now. A compatibility boot may start while those rows remain NULL,
but `/api/health` stays unready until explicit adoption succeeds. Adoption
requires an operator-authored JSON manifest backed by trusted evidence for the
attested adoption candidate whose exact bytes and invariants are being used as
proof. It does not claim to identify the unknown historical bytes:

    {
      "schema_version": 1,
      "artifact": {
        "engine_version": "0.1.0",
        "source_artifact": "<immutable artifact identifier>",
        "source_sha256": "<64 lowercase hex artifact digest>",
        "source_commit": "<40 or 64 lowercase hex source commit>"
      },
      "entries": [
        {
          "name": "0001_initial_schema",
          "content_sha256": "<64 lowercase hex from the audited applied module>"
        }
      ],
      "manifest_sha256": "<SHA256 of the canonical manifest payload>"
    }

The manifest must name the complete ordered history shipped by that artifact,
and each digest must also match its current module's exact bytes. Compute
`manifest_sha256` over the UTF-8 JSON encoding of only `schema_version`,
`artifact`, and `entries`, using sorted keys, no ASCII escaping, and separators
`,` and `:` with no extra whitespace. The deploy must supply that value again
as `--manifest-sha256`; changing the payload and recomputing its embedded digest
cannot satisfy the pinned value. Its engine version must match
`--running-version`, its source commit must match the separately supplied
`--source-commit`, and its artifact digest must match `--source-sha256`.

Those three trusted values come from deploy-owned release metadata, not from
the manifest or current checkout. The deploy surface is responsible for
verifying the selected artifact bytes against `--source-sha256`; the migration
runner compares the independently selected value and records it but does not
rediscover an artifact around its own source tree. Every entry being adopted
must expose `invariants(conn)` so the runner can prove equivalent database state
without executing `apply(conn)`.

If a permanent legacy module has no `invariants` function, do not edit that
released file. A project-owned runner may supply
`adoption_state_verifiers={"NNNN_name": callable}` to `migrate(...)`, or the
same mapping as `state_verifiers` when calling `adopt_from_manifest(...)`
directly. A registered callable receives the open SQLite connection and
replaces module invariants only for that exact name. Unknown names and
non-callables are refused. Verifiers execute inside the same rollback-only
savepoint as module invariants, so the project can keep permanent migration
bytes unchanged while proving equivalent live state.

Only then does one transaction fill NULL identity fields and insert an
immutable row in
`migration_adoption_receipts`. Update and delete triggers keep those receipts
append-only; each receipt preserves the adopted name/digest pairs and
`--adopted-by` records the accountable operator. Missing, extra, conflicting,
wrong-content, wrong-commit, wrong-source-digest, wrong-manifest-digest,
wrong-artifact-version, or failed-invariant manifests leave both the ledger and
receipt table unchanged.

Once the receipt table exists, readiness also requires both append-only
triggers. A dropped guard makes health and normal boot unsafe. Re-running the
explicit trusted adoption surface recreates either missing guard atomically,
even when no identity row remains to adopt; a fresh database with no receipt
table remains valid.

Run an audited adoption explicitly before normal boot:

    python3 app/db/migrations/migrate.py --running-version 0.1.0 \
      --source-commit <trusted-build-source-commit> \
      --source-sha256 <trusted-artifact-sha256> \
      --manifest-sha256 <trusted-manifest-sha256> \
      --adopted-by <operator-identity> \
      --adoption-manifest /secure/path/migration-adoption.json

The health response exposes content identity, ledger-ahead, and adoption
receipt guard state. A ledger row from a newer artifact remains a normal
rollback shape only when it records a non-empty serving floor compatible with
the running build. Its bytes are not compared with history the older artifact
does not ship. For common history, the recorded floor must exactly equal the
packaged declaration before its running-version comparison is trusted.

Every apply path requires a non-empty artifact version. Boot supplies the API
version; a manual run names it explicitly:

    python3 app/db/migrations/migrate.py --running-version 0.1.0

Before pending work, the runner creates a WAL-consistent, integrity-checked
backup under `app/data/migration-backups/`, or the directory selected by
`APP_MIGRATION_BACKUP_DIR`. `--external-restore-point` may name an already
established restore point instead. The result and any failure name the path or
external identifier; a current no-op boot creates no backup.

## Updating a customized migration runner

A project-owned runner may have a different ledger table, helper modules, or
health payload than this Pack's default. Do not resolve a three-way conflict by
blindly choosing either whole file. Preserve the project's ledger and restore
point flow while porting these behaviors: a nullable `content_sha256`, exact
raw-module hashing in the same transaction as each new membership write,
non-NULL mismatch refusal before backup or a current return, explicit NULL
adoption state, invariant-gated adoption, guarded append-only evidence, exact
known-floor parity, and identified ledger-ahead floors.

Use this gated sequence while the old build remains available:

1. Preview without checkout writes:

       yoke packs update webapp-scaffold <checkout> --project <slug> \
         --version 1.1.2 --json

2. Manually port every customized conflict and copy the additive helper files.
   Register project-owned state verifiers for permanent entries that do not
   already expose `invariants(conn)`. Run the project's tests and verify a NULL
   row reports `adoption_required`; the compatibility process may start, but
   readiness must remain false.
3. Build the audited manifest from immutable artifact evidence. With traffic
   stopped or against a restore-point copy, run the candidate migration CLI
   with `--adoption-manifest`, deploy-owned `--manifest-sha256`,
   `--source-sha256`, and `--source-commit` values, plus an accountable
   `--adopted-by`. Require no common-history NULL or mismatch afterward and
   inspect the append-only receipt.
4. Preview again, explicitly accepting only files whose project-owned merge was
   just verified. Repeat `--accept-current <path>` for each remaining conflict,
   then add `--apply` to that exact clean command. This writes source additions
   and then advances `.yoke/packs.json` to the verified Pack baseline.
5. Deploy and boot the candidate only after adoption evidence and health are
   green. Rollback still follows recorded serving floors and ledger-ahead rules.

## Relationship to other Packs

| Need | Pack |
|---|---|
| Docker and core-service runtime | container-runtime |
| Pulumi composition | pulumi-foundation |
| VPS provisioning | vps-hosting |
| DNS, API edge, and CDN | domain-cdn-edge |
| Registry and GitHub OIDC | registry-oidc |
| Production and hotfix delivery | production-deploy |
| Post-deploy smoke workflow | smoke-testing |
| Branch previews | ephemeral-environments |
| Host cleanup | host-maintenance |
| Managed Postgres infrastructure | managed-database |
| Self-hosted Actions runners | self-hosted-runners |

Installing another Pack does not make its project-specific gaps disappear;
read and complete that Pack's installed documentation.
