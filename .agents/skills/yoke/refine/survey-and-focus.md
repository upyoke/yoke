# Refine — Survey and Claims

Check recent commits and active items for renamed APIs, solved symptoms and
overlap; carry every finding into critique. File Budget and path
claims are independent axes; when both are on, they must match. With claims
on, a non-pass gate blocks; widen, never replace:
```bash
yoke claims path required-gate PREFIX-N
yoke claims path widen --claim-id <claim-id> --add-paths <added-paths> --reason "<verified-scope-expansion>" --item PREFIX-N
```
