"""Help epilogs for governed migration apply."""

SELF_MIGRATION_TEMP_RECIPE = """\
Temporary pre-ephemeral Yoke self-migration recipe:

Use this only until worktree/SHA ephemeral envs can hydrate prod data and run
the rehearsal in-env/VPC. It is for small additive Yoke self-migrations that
must be applied manually during /yoke advance. If the item's deployment flow
will run migration_apply later, do not also live-apply manually.

Run from the item worktree after the implementation commit, while holding the
work-claim. The item db_mutation_profile must declare mutation_intent=apply
and migration_modules=[SLUG].

  ITEM=1898
  SLUG=<migration_module_slug>
  WT="$(git rev-parse --show-toplevel)"
  MODULE="$WT/runtime/api/domain/migrations/$SLUG.py"
  VALDB="yoke_test_sun${ITEM}_validation"

  # 1. Back up prod Aurora with a manual RDS cluster snapshot. The cluster
  #    identifier is operator topology (find yours via
  #    `aws rds describe-db-clusters`); the example below is generic.
  GET_SECRET="python3 -m yoke_core.domain.projects capability-get-secret"
  export AWS_ACCESS_KEY_ID="$($GET_SECRET yoke aws-admin access_key_id)"
  export AWS_SECRET_ACCESS_KEY="$($GET_SECRET yoke aws-admin secret_access_key)"
  export AWS_DEFAULT_REGION=us-east-1
  CLUSTER=<prod-db-cluster-identifier>   # e.g. myproject-prod-aurora
  SNAP="${CLUSTER}-pre-yok${ITEM}-$(date +%Y%m%d-%H%M%S)"
  aws rds create-db-cluster-snapshot --db-cluster-identifier "$CLUSTER" --db-cluster-snapshot-identifier "$SNAP"
  aws rds wait db-cluster-snapshot-available --db-cluster-snapshot-identifier "$SNAP"
  echo "backup ready: $SNAP"

  # 2. Provision local validation. Set ONLY YOKE_PG_DSN_VALIDATION.
  #    Do not eval pg_testcluster env and do not set YOKE_PG_DSN, because
  #    YOKE_PG_DSN is the authoritative/live target selector.
  python3 -m yoke_core.tools.pg_testcluster start >/dev/null
  SOCK="$(python3 -m yoke_core.tools.pg_testcluster env | sed -n 's/.*host=\\([^ ]*\\) .*/\\1/p')"
  psql -h "$SOCK" -U yoketest -d postgres -Atc "DROP DATABASE IF EXISTS $VALDB;"
  psql -h "$SOCK" -U yoketest -d postgres -Atc "CREATE DATABASE $VALDB;"
  export YOKE_PG_DSN_VALIDATION="host=$SOCK user=yoketest dbname=$VALDB"

  # 3. Rehearse against validation while authoritative remains prod.
  cd "$WT"
  python3 -m yoke_core.domain.migration_apply rehearse "$ITEM" --module-path-override "$MODULE"

  # 4. Operator checkpoint, then live-apply to prod.
  python3 -m yoke_core.domain.migration_apply live-apply "$ITEM" --module-path-override "$MODULE"

  # 5. Verify and commit the auto-retire deletion.
  python3 -m yoke_core.cli.db_router query "SELECT migration_name, state FROM migration_audit WHERE migration_name='$SLUG' ORDER BY id DESC LIMIT 1"
  git -C "$WT" add -A
  git -C "$WT" commit -m "YOK-$ITEM: retire $SLUG post-live-apply"

  # 6. Teardown local validation; keep the RDS snapshot until settled.
  psql -h "$SOCK" -U yoketest -d postgres -Atc "DROP DATABASE IF EXISTS $VALDB;"
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY YOKE_PG_DSN_VALIDATION

Important:
  - --module-path-override is required for unmerged worktree modules.
  - Never point YOKE_PG_DSN at pg_testcluster during live apply.
  - Local validation is a temporary fallback. From an in-VPC shell, prefer the
    future clone/ephemeral rehearsal path for production-data fidelity.
"""
