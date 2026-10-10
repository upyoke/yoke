# GitHub Actions workflow conditions

GitHub does not support direct `secrets.*` references in `if:` conditions.
Pass non-AWS credentials through `env:` and check them inside a step, or use
the job environment to conditionally run steps. An unset secret expands to an
empty string. See [GitHub's secret guidance](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy when configured
        env:
          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
        run: |
          if [ -z "$DEPLOY_KEY" ]; then
            echo "DEPLOY_KEY not set — skipping deploy"
            exit 0
          fi
          # Required deploy logic follows.
```

AWS delivery is required work, not an optional secret-gated step. Grant minimum
OIDC permissions and assume the IaC-owned role through a reviewed action revision;
credential failure fails the stage. Long-lived AWS access keys are unsupported.

```yaml
permissions:
  contents: read
  id-token: write

steps:
  - uses: actions/checkout@v4
  - name: Configure AWS delivery credentials
    uses: aws-actions/configure-aws-credentials@<reviewed-commit-sha>
    with:
      role-to-assume: ${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}
      aws-region: us-east-1
  - name: CloudFront invalidation
    run: aws cloudfront create-invalidation --distribution-id "$CF_ID" --paths "/*"
```

The production-deploy Pack owns the reviewed pin, CloudFront discovery,
bounded diagnostics and fail-closed behavior. Read its capability settings
rather than invent a credential path.

Yoke enforces the conditional restriction in the shared Python write policy
`yoke_core.domain.lint_write_path` and the Bash guard `lint_db_cmd`
(stable audit id `lint-sqlite-cmd`). Workflow YAML writes through Write or
Bash heredoc/cat/tee/redirection are checked before effects; no separate lint
script owns a second rule. A refusal names file/line and the env/run recovery.

The predicate remains narrow: secret references in `env:`, `run:`, step `with:`
or comments are permitted; `success()`, `failure()` and `always()` conditions
without a secret reference are permitted.
