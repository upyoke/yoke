# Move the operator projects into Stage

This attended operation moves a whole universe through the product export and
Import path. Run it after Yoke and Platform releases expose those controls.
Prune first, export with artifacts, import, verify, then resume or retire the source.
Do not continue independent work against both copies.

## Bind the operation

Record in the move item's Progress Log: source and destination orgs and tenant
ids; three moved project ids/slugs;
checkout paths; source pause/resume authority; outage window; rollback
window; and owner for each step. Substitute these recorded values below.
`DESTINATION` is the new Stage org's HTTPS connection. Keep any archive in an owner-only directory outside Git; never record signed
links, tokens or credentials in the Progress Log.

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

6. Estimate and prune before pausing the source. Hosted sources use
   **Download** on the dashboard's **Move universe** page; its size preflight
   enforces a 10 GiB cap before pausing, and its signed link lasts one hour.
   Local and self-host sources use the active source connection:

   ```text
   yoke universe export --estimate --json
   yoke universe export --pause-source --out /secure/source.tar
   yoke universe validate /secure/source.tar
   ```

   Export checks output-folder write access before pausing and refuses an
   unavailable path without stopping writers. The pause disables source database connections, drains all client sessions and
   creates a frozen copy before
   the snapshot. It stays in effect after either success or failure until Resume.
   A backup export without the flag cannot be used for hosted replacement.
   Hosted CLI export refuses and names dashboard Download; protected direct
   database connections do not bypass the dashboard.

7. On the destination dashboard's **Move universe** page, paste the hosted
   source's signed link into **Import**. For a local or self-host archive:

   ```text
   yoke --env DESTINATION universe upload /secure/source.tar --org DESTINATION_ORG
   ```

   Follow the printed dashboard path to finish Import. The archive streams
   directly to signed multipart storage targets. There is no browser upload
   or separate source-bucket copy: import fetches from configured source
   buckets and restores artifacts before the destination serves.
   Save the receipt and rollback deadline. Compare project, item, actor and
   dependency counts and verify identity links and sample artifact reads.
   Finish steps 7–10 within the recorded rollback window. Rollback also
   requires rebinding repositories on Production before resuming merges.
   Resume the hosted source through **Resume source**, or run
   `yoke universe resume` against a local/self-host source. Verify people
   staying there can sign in and read their work. An export that fails after pausing also needs
   explicit Resume before normal work can continue.

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

9. Read sample QA evidence and shared files through the destination.
   Compare artifact checksums and missing-file reports with the archive
   manifest. Repair missing source files and export again if needed; do not
   infer successful restoration from database counts alone.

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

16. After the rollback window and artifact checks pass, retire the old
    source only if nobody still uses it. In a shared source universe, retire
    only the moved project copies through their product commands. Preserve
    the receipt and archive according to the operator's recovery policy.

17. Inventory project-creating tests and QA routes before reopening work:
    `rg -n 'projects create|insert_project|INSERT INTO projects' runtime tests`.
    Check each real-data test/QA connection targets Stage and remains protected;
    disposable isolated fixtures retain their declared test database owner.
    Record the inventory and final no-flag checkout routing checks.

## Recovery

Before import, use Resume source on a hosted source, or `yoke universe resume`
on a local/self-host source, even after an export failure. After import, use
the destination's latest replacement and its exact typed rollback confirmation
within the recorded window; rollback discards later destination writes.
Stop destination work first and preserve receipts. Rebind repositories on
Production through Platform's cutover runbook before resuming merges after rollback.
