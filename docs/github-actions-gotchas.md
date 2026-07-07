# GitHub Actions Gotchas

Platform limitations and anti-patterns in GitHub Actions workflow files.

## secrets.* in if: conditions

**Severity:** Catastrophic (silent, zero-feedback failure)

### The Problem

GitHub Actions silently fails to parse workflows when `secrets.*` appears in `if:` conditions. The entire workflow shows **zero jobs** with no error message — not even a syntax error in the Actions UI.

```yaml
# WRONG — this silently breaks the entire workflow:
jobs:
 deploy:
 if: ${{ secrets.DEPLOY_KEY != '' }}
 runs-on: ubuntu-latest
 steps: ...
```

When this workflow triggers, GitHub shows "0 jobs" and no runs appear. There is no log, no error, no indication of what went wrong.

### Why It Happens

GitHub evaluates `if:` conditions during workflow parsing, before any job context exists. The `secrets` context is not available at parse time for `if:` conditions at the job or step level in certain evaluation paths. Instead of raising an error, GitHub silently drops the entire workflow.

### The Fix

Pass secrets via `env:` and check the environment variable in `run:`:

```yaml
# RIGHT — pass via env, check in run:
jobs:
 deploy:
 runs-on: ubuntu-latest
 steps:
 - name: Deploy (if key available)
 env:
 DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
 run: |
 if [ -z "$DEPLOY_KEY" ]; then
 echo "DEPLOY_KEY not set — skipping deploy"
 exit 0
 fi
 # ... deploy logic here
```

For conditional steps that should skip entirely:

```yaml
 - name: CloudFront invalidation
 if: success()
 run: |
 if [ -z "$AWS_ACCESS_KEY_ID" ]; then
 echo "AWS_ACCESS_KEY_ID not set — skipping CloudFront invalidation"
 exit 0
 fi
 aws cloudfront create-invalidation --distribution-id "$CF_ID" --paths "/*"
 env:
 AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
 AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### Automated Guards

Yoke has three layers of protection against this anti-pattern:

1. **PreToolUse Write hook** (`lint-write-path.sh`): Blocks Write tool calls that would create workflow YAML files containing `secrets.*` in `if:` conditions.

2. **PreToolUse Bash hook** (`yoke_core.domain.lint_db_cmd`, legacy stable check id `lint-sqlite-cmd`, Check 8): Blocks Bash commands that write workflow content with this pattern via heredocs, cat, tee, or redirects.

3. ~~Standalone lint script~~ (`lint-workflow-secrets.sh`): Deleted. Superseded by `lint-write-path.sh` Check 2.

### Safe Uses of secrets.*

The lint checks are scoped narrowly. These patterns are **safe** and will NOT trigger:

- `secrets.*` in `env:` blocks (the recommended pattern)
- `secrets.*` in `run:` blocks (e.g., inline shell references)
- `secrets.*` in step `with:` parameters
- `secrets.*` in comments
- `if: success()`, `if: failure()`, `if: always()` (no secrets reference)
