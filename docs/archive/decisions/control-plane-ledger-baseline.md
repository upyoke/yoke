# Control-plane ledger baseline

The control plane has only the eight hosted Stage and Production tenant
databases. Their ledgers have every packaged migration through ordinal 0106,
with verified content identities. There are 102 entries because the ordinal
sequence has gaps. There are no local or self-hosted installs to carry forward.

The release carrying `0106_baseline` removes their scripts and declares one
fixed baseline identity in the history package. Births record only that row.
An existing tenant must have the exact predecessor names and digests before
boot replaces them with the baseline. The frozen predecessor manifest is
temporary transition input, never active migration history.

The replacement runs under the normal migration apply lock and a table lock,
with a restore point. It changes only the migration ledger. A savepoint keeps
the replacement atomic, and repeat boot changes nothing. Only the declared
delete guard is suspended, for the single deletion statement; it is restored
before the baseline row is inserted. Failure restores both membership and
trigger state without rolling back unrelated caller work.

**Release note: after a tenant ledger collapses, rollback to any release older
than the release carrying this baseline is unsupported.** The new row records
the carrying release as its serving floor. Recovery uses a database restore
point together with its matching older release, or proceeds forward.

Old archive import adapters are removed. Portable archives use the current
trusted schema and retain their immutable evidence; the loader does not
reconstruct retired tables, translate retired column names, or backfill old
QA execution snapshots.

After Stage and Production prove that all eight ledgers contain the baseline,
a following release removes the predecessor manifest and boot collapse step.
The code-declared baseline identity remains unchanged, with no migration scripts
or permanent history manifest required.
