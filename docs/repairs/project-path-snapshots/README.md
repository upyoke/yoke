# Remove scratch checkout snapshots

These reviewed documents remove two unrelated QA checkout snapshots and rows
referenced only by them. Run them in filename order, one at a time. For each,
obtain operator approval for the digest below, run the guarded simulation, check
its durable audit, then apply the same document. Do not skip a failed document.
The runner needs the live project steering seat and organization admin authority;
this item's worker prepares the repair but does not hold that seat.

| Document | SHA-256 |
|---|---|
| 01-symlink-facts.json | 3a7363bcba5a7d92d57bcd1683edeee837bd6f8b954a7dc47731ee270a5c12b3 |
| 02-entries.json | 0489f0b47707ae032226e3362d5cac49db618a4d2d7bbcd3a4303bf38a3755b2 |
| 03-entries.json | 6ef87c5582c1af84b1a3f7d8c357558d6909e51d4c8dfabe564cb6400fd477a5 |
| 04-snapshots.json | ddc5344240374c6c6a31d5f3c829da64a85e0b8047cdebfa6ed35190d29fd068 |
| 05-unreferenced-targets.json | 47f69db5ce338a048f58f726261f125a9f2fcb8981f50e73690f76ebd27f1a2d |

From this directory, replacing FILE and DIGEST with the reviewed row:

```text
yoke operator data-repair --content-file FILE --reviewed-sha256 DIGEST --dry-run
yoke operator data-repair --content-file FILE --reviewed-sha256 DIGEST
```

Read the returned audit with `yoke db read` as described in the
[repair contract](../../public/databases/operator-data-repair.md).
The documents cover one symlink fact, 514 entries, two snapshots and 57 targets.
Diagnosis found no claim, context, integrity-failure, move, outside-snapshot entry,
or outside child reference to the 57 targets. The guarded repair rechecks the
reviewed rows and foreign keys rather than assuming that observation stays true.
Afterward, read the two snapshot ids and confirm no rows remain, then sync the
real checkout to refresh architecture context if needed.

Steering completed the repair: applied audits 9102, 9104, 9106, 9109 and 9111;
corresponding simulations 9101, 9103, 9105, 9108 and 9110. Audit 9107 refused
the original timestamp spelling; the last two documents now preserve the
approved `Z` timestamps and digests. Steering verified both snapshot ids absent.
