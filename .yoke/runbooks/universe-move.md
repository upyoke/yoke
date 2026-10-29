# Move the operator projects into Stage

This is an attended operation, not a deploy recipe. Run it only after the
Yoke engine and Platform hosted-import companion are released. It copies a
whole tenant; retire unwanted project copies afterward. Production remains
live for the people and projects staying there. Do not run `quiesce retire`.

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

## Ordered execution and checks

1. Show the operator the final release-policy text, then update the existing
   instruction with `yoke workflow execution-instruction update INSTRUCTION_ID
   --content "APPROVED_TEXT"`; preserve its delivery settings. Record approval
   and the returned instruction. Stage becomes durable real work; Production
   follows Stage QA except for the urgent hotfix route.

2. Create the empty destination Stage org through hosted organization setup.
   Both people sign in and join with their intended roles before import.
   Check the org's members in the dashboard and compare linked actor ids with
   `yoke --env DESTINATION db read "SELECT id, name FROM actors ORDER BY id"`.
   Resolve identity gaps with `yoke identity link set --help` before draining.

3. Pause merges for the three moved repositories. Read each project's items,
   claims and runs through its owning Production connection; ask live holders
   to checkpoint and release. Cancel pending launches and finish or cancel
   active runs using their ordinary owners. Leave open items open to copy.
   Check `yoke --env prod claims work holder-list --help` and the live fleet
   report; no moved-project worker, merge-queue entry or run may remain.
   Keep other projects and their GitHub bindings intact.

4. Protect every destination database-admin profile on every operator machine:

   ```text
   yoke connection set stage-db-admin --protected
   yoke config status
   ```

   Check the connection reports `protected=true`; environment names alone do
   not establish safety. Do not clear Production's marker.

5. During the attended outage, use the recorded Platform service-control owner
   to stop the source tenant API, synchronization and webhook writers. Record
   its stop receipt; no replacement operation substitutes for this stop.
   Run the source boundary, which proves the database fence itself:

   ```text
   yoke --env SOURCE_ADMIN source-authority quiesce begin --service-stop-receipt STOP_RECEIPT --credential-file /secure/source-cutover.json --json
   yoke source-authority quiesce status --credential-file /secure/source-cutover.json --json
   yoke source-authority export --out /secure/source.tar --credential-file /secure/source-cutover.json --json
   yoke universe validate /secure/source.tar
   yoke source-authority quiesce abort --credential-file /secure/source-cutover.json --json
   ```

   Check begin/status prove the fence, export publishes a validated archive,
   and abort restores the source's credentials and CONNECT policy. Restart
   the same source service immediately through its recorded owner. Verify
   the person staying on Production can sign in and read their existing work
   before continuing. A failed export still requires abort and restart.

6. In `https://app.stage.upyoke.com/orgs/DESTINATION_ORG/tenant-replacement`,
   upload the archive and execute the hosted replacement's attended checks.
   The console owns import and latest-replacement recovery; there is no Yoke
   CLI import route for a hosted tenant. Save its receipt and rollback deadline.
   Check the receipt records copied-token/session revocation before destination
   credential issuance and records `artifact_prefix_map`. Compare source and
   destination project, item, actor and dependency counts before retirement.
   Finish the remaining checks within the recorded rollback window.

7. On Stage, declare destination `aws-admin` capabilities for the two release
   projects with `yoke --env DESTINATION projects capability --help` and their
   reviewed declarations. Destination-owned capability settings and secrets
   survive import; a new org starts empty. Machine-held capability-secret
   files remain keyed by unchanged project slugs. Rebind `stage-db-admin` to
   the new tenant through `yoke dev db-admin setup --help`, keeping protection.
   Check capabilities resolve through Stage before running any release.

8. Copy each prefix from the import receipt, using only the moved projects:

   ```text
   aws s3 sync SOURCE_PREFIX/PROJECT/ DESTINATION_PREFIX/PROJECT/ --dryrun
   aws s3 sync SOURCE_PREFIX/PROJECT/ DESTINATION_PREFIX/PROJECT/
   aws s3 ls DESTINATION_PREFIX/PROJECT/ --recursive --summarize
   ```

   Repeat for `qa-artifacts` and `shared-files` for all three project slugs.
   Use the receipt's exact bucket and tenant prefixes; never infer them from
   an environment label. Record object counts and read sample QA evidence
   and shared files through Stage. Do not delete source objects yet.

9. Provision each machine against Stage with destination-issued credentials;
   do not reuse copied tokens. `yoke tokens create --name MACHINE_NAME` shows
   a secret once: capture it privately, never into the Progress Log. Store it
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

10. Execute Platform's GitHub cutover runbook for the three moved repos:
    unbind on Production, deselect them from its installation, install Stage's
    App and reconcile on Stage. Keep merges paused until Stage proves each
    binding and Production no longer binds it. Never bind both tenants to
    the same repository. Platform owns the exact hosted routes and receipts.

11. On Stage, cancel open items in the projects staying on Production and in
    unwanted QA fixture projects, after checking that none is a moved project.
    Retire each reviewed unwanted project:

    ```text
    yoke --env DESTINATION projects retire --project PROJECT --reason "Unwanted copy after attended tenant move"
    yoke --env DESTINATION projects list --include-retired
    ```

    Check retired history remains readable. Open items, active runs and held
    claims refuse retirement; finish those obligations rather than bypassing.

12. On Production, cancel the moved projects' open copies, including the move
    item's source copy, and retire only those three projects with the same
    command using `--env prod`. Continue work through the Stage copy.
    Verify the remaining person's org, URL, token, checkouts, GitHub binding
    and open items still work. A failed check stops source cleanup.

13. After verified Stage artifact reads, record before counts and delete only
    each moved project's two source prefixes:

    ```text
    aws s3 ls SOURCE_PREFIX/PROJECT/ --recursive --summarize
    aws s3 rm SOURCE_PREFIX/PROJECT/ --recursive --dryrun
    aws s3 rm SOURCE_PREFIX/PROJECT/ --recursive
    aws s3 ls SOURCE_PREFIX/PROJECT/ --recursive --summarize
    ```

    Review dry-run paths against the three-project allowlist; never remove a
    whole tenant prefix. Record after counts and unchanged remaining-project
    prefixes. Keep the import receipt and archive private for rollback.

14. From the Stage-owned project, create one Stage self-release and one
    Production release through their live bound flows. Follow `deploy.md`;
    creation uses Stage HTTPS, the self-release driver uses `stage-db-admin`,
    and the Production target uses the owning Stage HTTPS connection. Record
    both exact source revisions, run ids, promotion receipts and owed QA.

15. Inventory project-creating tests and QA routes before reopening work:
    `rg -n 'projects create|insert_project|INSERT INTO projects' runtime tests`.
    Check each real-data test/QA connection targets Stage and remains protected;
    disposable isolated fixtures retain their declared test database owner.
    Record the inventory and final no-flag checkout routing checks.

## Recovery

Before import, abort the fence and restart Production even if export fails.
After import, use the destination console's latest replacement and exact typed
rollback confirmation within its recorded window; rollback discards writes
made after replacement. Stop destination work first and preserve receipts.
After source artifact deletion, recovery also needs the verified Stage copy.
Never disable Production's administrator with `quiesce retire` during this move.
