# CLI usage contracts

Keep handwritten usage strings in sync with the parser.
Include every visible option, including flags added by shared helpers, and use
a registered command path. Internal options use `help=argparse.SUPPRESS`.
Keep each recipe with its existing owner and reuse it in error messages;
changes to a command update its owning usage in the same commit.

`runtime/api/cli/test_adapter_usage_contract.py` constructs every
registered adapter and alias parser without parsing or executing the command.
It checks explicit `usage=` text and handwritten error recipes, excluding
hidden options and argparse's automatic help flag. The audit retains handwritten
usage; argparse-generated help continues to describe parsers that already use it.

Run the focused check from the claimed lane:

```text
yoke watch pytest --local -- runtime/api/cli/test_adapter_usage_contract.py
```

The checker catches omitted shared flags, stale command paths, and partial
flag-name matches. Hidden flags need no usage entry.
