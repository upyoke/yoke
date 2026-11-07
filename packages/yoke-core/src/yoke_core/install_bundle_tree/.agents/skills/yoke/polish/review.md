# Polish — review and fix

Read `yoke items get PREFIX-N spec technical_plan test_results`. Compare each
lane with recent main and active items; carry drift and overlap into review.

1. Walk each lane's diff once for reuse, quality and efficiency together.
   Stay inside the diff; no parallel agents. Fix inline.
2. Review each lane's `git diff main...HEAD` and uncommitted changes against
   every AC. The change must work end to end where users meet it. Delete dead
   code, tests and shims, but never permanent migration modules. Leave zero
   residue after renames. Run `yoke check file-line --base main`.
3. Fix gaps in their owning lane; flag new features to the operator. An
   undeclared DB mutation stops work until `yoke db-claim amend`.

Next: [verify-and-commit](verify-and-commit.md).
