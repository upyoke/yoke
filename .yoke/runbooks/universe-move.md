# Move the operator projects into Stage

This is an attended operation, not a deploy recipe. Run it only after the
Yoke engine and Platform hosted-import companion are released. It copies a
whole tenant; retire unwanted project copies afterward. Step 6 is a planned
off-hours Production outage; restore service immediately after export for the
people and projects staying there. Do not run `quiesce retire`.

## Bind the operation

Record in the move item's Progress Log: source and destination orgs and tenant
ids; source and destination artifact buckets; three moved project ids/slugs;
checkout paths; source service-stop/start authority; outage window; rollback
window; and owner for each step. Substitute these recorded values below.
`SOURCE_ADMIN` is the protected source database-admin connection;
`DESTINATION` is the new Stage org's HTTPS connection. Keep the archive and
cutover credential bundle in an owner-only directory outside Git.

Before the outage, prove both releases contain the import helpers; read the
live versions with `yoke --env prod status` and `yoke --env stage status`.
On each machine, confirm command help accepts `--protected` before proceeding.

## Before the window

0. Correct and land this runbook before starting the attended operation.
   Steps 1–17 require the operator present; do not run them as part of the
   runbook correction.

## Ordered execution and checks

1. Create the empty destination Stage org through hosted organization setup.
   The operator and Justin sign in and join with their intended roles before
   import; credentials are minted only for current members with a role.
   On Production, confirm or set each verified Google identity link before
   export, using the person's verified issuer subject:
   `yoke --env prod identity link set --actor ACTOR_ID --issuer https://accounts.google.com --subject VERIFIED_SUBJECT`.
   Links set on Stage before import are overwritten; verify them after import.

2. Steering hand-off: release every steering-held claim on the moving
   projects, including this item's Production copy. Run steps 3–9 from a plain
   terminal; hooks may block during the outage.

3. Drain the three moving projects. Read each project's items, claims and runs through its owning Production connection; ask live holders
   to checkpoint and release. Cancel pending launches and finish or cancel
   active runs using their ordinary owners. Leave open items open to copy.
   Read each moved project's obligations, paging every returned cursor:

   ```text
   yoke --env prod items list --project PROJECT --fields id,status,title --limit 1000
   yoke --env prod claims work holder-list --item ITEM
   yoke --env prod sessions list --project PROJECT --liveness active
   yoke --env prod deployment-runs list --project PROJECT --status created
   yoke --env prod deployment-runs list --project PROJECT --status executing
   ```

   Check the live fleet report too; no moved-project worker, merge-queue entry
   or run may remain.
   Keep other projects and their GitHub bindings intact.

4. Before export, pause merges and follow Platform's
   `docs/runbooks/github-tenant-cutover.md`: unbind the three projects on
   Production, deselect their repositories from Production's GitHub App
   installation, then install Stage's App on those repositories. Keep merges
   paused until step 11; leave Justin's projects and bindings untouched.

5. Protect every destination database-admin profile on every operator machine:

   ```text
   yoke connection set stage-db-admin --protected
   yoke config status
   ```

   Check the connection reports `protected=true`; environment names alone do
   not establish safety. Do not clear Production's marker.

6. During the attended outage, on the recorded Production host, stop its
   Platform writers and source tenant server. `SOURCE_COMPOSE_FILE` is the
   absolute installed `docker-compose.platform.yml`; `SOURCE_CONTAINER` is
   the tenant container verified against registry identity and Docker labels,
   never a name guessed from the org slug. Save the command results as the
   stop receipt, then run the source boundary from the operator machine:

   ```text
   docker compose -f SOURCE_COMPOSE_FILE stop webapp platform-svc
   docker stop SOURCE_CONTAINER
   docker inspect --format '{{.Name}} {{.State.Running}}' SOURCE_CONTAINER
   docker compose -f SOURCE_COMPOSE_FILE ps --status running webapp platform-svc
   ```

   Check the tenant is stopped and neither Platform writer is running. The
   database fence below independently proves no ordinary writer remains:

   ```text
   yoke --env SOURCE_ADMIN source-authority quiesce begin --service-stop-receipt STOP_RECEIPT --credential-file /secure/source-cutover.json --json
   yoke source-authority quiesce status --credential-file /secure/source-cutover.json --json
   yoke source-authority export --out /secure/source.tar --credential-file /secure/source-cutover.json --json
   yoke universe validate /secure/source.tar
   yoke source-authority quiesce abort --credential-file /secure/source-cutover.json --json
   ```

   Check begin/status prove the fence, export publishes a validated archive,
   and abort restores the source's credentials and CONNECT policy. On the
   same host, restart and check the declared services immediately:

   ```text
   docker start SOURCE_CONTAINER
   docker compose -f SOURCE_COMPOSE_FILE start platform-svc webapp
   docker inspect --format '{{.State.Running}}' SOURCE_CONTAINER
   docker compose -f SOURCE_COMPOSE_FILE ps --status running webapp platform-svc
   ```

   Check the tenant and both Platform services are running. Verify
   the person staying on Production can sign in and read their existing work
   before continuing. A failed export still requires abort and restart.

7. In `https://app.stage.upyoke.com/orgs/DESTINATION_ORG/tenant-replacement`,
   fill the source artifact bucket and source tenant fields, upload the
   archive and execute the hosted replacement's attended checks.
   The console owns import and latest-replacement recovery; there is no Yoke
   CLI import route for a hosted tenant. Save its receipt and rollback deadline.
   Check the receipt records copied-token/session revocation before destination
   credential issuance and records `artifact_prefix_map`. Compare source and
   destination project, item, actor and dependency counts before retirement.
   Verify identity links on Stage. Finish steps 7–10 within the recorded
   24-hour rollback window. A rollback also requires rebinding the repositories
   on Production before resuming merges.

8. On Stage, declare destination `aws-admin` capabilities for the two release
   projects using each reviewed non-secret settings document:
   `yoke --env DESTINATION projects capability-settings set --project PROJECT --cap-type aws-admin --settings-json SETTINGS_JSON --new`.
   Use the existing settings as `--base BASE_JSON` instead of `--new` if present. Destination-owned capability settings and secrets
   survive import; a new org starts empty. Machine-held capability-secret
   files remain keyed by unchanged project slugs. Rename the existing Stage
   connection pair from `stage` / `stage-db-admin`
   to `stage-1` / `stage-1-db-admin`, then create `stage` for the new org.
   Point `stage-db-admin` at the destination tenant's verified managed DSN
   secret, keeping protection:
   `yoke dev db-admin setup --admin-env stage-db-admin --control-plane-env stage --secret-name DESTINATION_TENANT_DSN_SECRET --protected --yes`.
   The admin profile pairs with the connection named `stage`; record the
   renamed and new connection identities before changing checkout routing.
   Check the setup receipt's database identity matches the import receipt.
   Check capabilities resolve through Stage before running any release.

9. Copy each prefix from the import receipt, using only the moved projects:

   ```text
   aws s3 sync SOURCE_PREFIX/PROJECT/ DESTINATION_PREFIX/PROJECT/ --dryrun
   aws s3 sync SOURCE_PREFIX/PROJECT/ DESTINATION_PREFIX/PROJECT/
   aws s3 ls DESTINATION_PREFIX/PROJECT/ --recursive --summarize
   ```

   Repeat for `qa-artifacts` and `shared-files` for all three project slugs.
   Use the receipt's exact bucket and tenant prefixes; never infer them from
   an environment label. Record object counts and read sample QA evidence
   and shared files through Stage. Do not delete source objects yet.

10. Provision each machine against Stage with destination-issued credentials;
    do not reuse copied tokens. `yoke tokens create --name MACHINE_NAME` shows
    a secret once: capture it privately, never into the Progress Log. Select
    `--env DESTINATION` explicitly when creating that token. Store it
    with `yoke connection set DESTINATION --transport https --protected
    --api-url DESTINATION_API --token-file PRIVATE_TOKEN_FILE`, then:

    ```text
    yoke --env DESTINATION machine register --name MACHINE_NAME
    yoke --env DESTINATION project register CHECKOUT --project-id PROJECT_ID --reassign
    yoke --env DESTINATION relay install
    yoke projects checkout-context
    yoke session-control launch preview --help
    ```

    Repeat registration for each checkout. Check its reported connection is
    Stage without `--env`, and check fresh launch capacity before ending the
    old machine route.
    End the old steering session; continue in a new session on Stage, using
    explicit `--env prod` for Production writes.

11. Reconcile the three moved repositories on Stage's GitHub page using
    Platform's cutover runbook. Confirm Stage proves each binding and
    Production no longer binds it, then resume merges. Never bind both tenants
    to the same repository.

12. On Stage, cancel open items in the projects staying on Production and in
    unwanted QA fixture projects, after checking that none is a moved project.
    Retire each reviewed unwanted project:

    ```text
    yoke --env DESTINATION projects retire --project PROJECT --reason "Unwanted copy after attended tenant move"
    yoke --env DESTINATION projects list --include-retired
    ```

    Check retired history remains readable. Open items, active runs and held
    claims refuse retirement; finish those obligations rather than bypassing.

13. On Production, cancel the moved projects' open copies, including the move
    item's source copy, and retire only those three projects with the same
    command using `--env prod`. Continue work through the Stage copy.
    Verify the remaining person's org, URL, token, checkouts, GitHub binding
    and open items still work. A failed check stops source cleanup.

14. From the Stage-owned project, create one Stage self-release and one
    Production release through their live bound flows. Follow the live bound
    release skill and source-dev doctrine;
    creation uses Stage HTTPS, the self-release driver uses `stage-db-admin`,
    and the Production target uses the owning Stage HTTPS connection. Record
    both exact source revisions, run ids, promotion receipts and owed QA.

15. Switch the release policy only after step 14 proves release control.
    Show the operator this final text first, then update instruction 199 with
    `yoke workflow execution-instruction update`, preserving delivery settings:

    > Release policy (Yoke + Platform). Stage gets frequent releases from main through `yoke-hosted-stage-release-qa` and is a durable home for real work. Production gets only a version that has already passed its Stage release QA, through `yoke-hosted-production-release-qa`. Production is never released ahead of Stage, except through the hotfix flow for an urgent production fix.

    Record the final text and returned instruction in the Progress Log. Until
    this step, the operator's attended run overrides the old release policy.

16. After the rollback window has passed and step 9 artifact reads are
    verified, record before counts and delete only each moved project's two
    source prefixes:

    ```text
    aws s3 ls SOURCE_PREFIX/PROJECT/ --recursive --summarize
    aws s3 rm SOURCE_PREFIX/PROJECT/ --recursive --dryrun
    aws s3 rm SOURCE_PREFIX/PROJECT/ --recursive
    aws s3 ls SOURCE_PREFIX/PROJECT/ --recursive --summarize
    ```

    Review dry-run paths against the three-project allowlist; never remove a
    whole tenant prefix. Record after counts and unchanged remaining-project
    prefixes. Keep the import receipt and archive private as recovery evidence.

17. Inventory project-creating tests and QA routes before reopening work:
    `rg -n 'projects create|insert_project|INSERT INTO projects' runtime tests`.
    Check each real-data test/QA connection targets Stage and remains protected;
    disposable isolated fixtures retain their declared test database owner.
    Record the inventory and final no-flag checkout routing checks.

## Recovery

Before import, abort the fence and restart Production even if export fails.
After import, use the destination console's latest replacement and exact typed
rollback confirmation within its recorded window; rollback discards writes
made after replacement. Stop destination work first and preserve receipts.
Rebind the three repositories on Production through Platform's cutover runbook before
resuming merges after rollback.
After source artifact deletion, recovery also needs the verified Stage copy.
Never disable Production's administrator with `quiesce retire` during this move.
