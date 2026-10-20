# Conduct — output retries

Missing output is not a FAIL and uses no attempt. Two retries, then fallback.

- Tester: render the minimal variant of
  [the shared Tester template](../shared/tester-dispatch-template.md)
  (retry 2 escalates the model), then [dispatch-context-verify.md](dispatch-context-verify.md).
- Simulator: retry 1 demands the two header lines; retry 2 allows no tools and
  at most 3 gaps. Then halt; never write CLEAN yourself.
