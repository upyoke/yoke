# Testing Verification Recipes

Ruff is a locked development dependency. Lint every changed Python path with:

```bash
uv run --frozen ruff check <changed Python paths>
```

Do not call a checkout-local `.venv/bin/ruff` path or rely on an ambient
Homebrew install.

For a changed-test fallback, first list candidates with:

```bash
git diff --name-only --diff-filter=ACMR <base>...HEAD \
  -- ':(glob)**/test_*.py' ':(glob)**/*_test.py'
```

Review the newline-delimited output, then pass the exact existing paths to
`watch_pytest`. Do not pipe NUL-delimited Git output through `rg -z`, and never
feed a filter diagnostic to pytest as a filename.
