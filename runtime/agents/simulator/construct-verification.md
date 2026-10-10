# Simulator — Construct Verification

Read before any specific code reference in a gap. Constructs include HC ids,
functions/methods, vars/env names, file paths, config/policy keys, tables/columns,
routes/commands/events. Verify EACH with at least one scoped search/file read
against live source/schema. Definition/actual assignment/use matters, not a
similar noun phrase in teaching prose.

Normal dispatch: unverifiable reference is dropped or gap reformulated without
it; never fabricate. Restricted compressed/retry dispatch: if tool verification
is unavailable, mark construct `[UNVERIFIED]`, explain restriction in root cause
and downgrade one severity (CRITICAL→WARNING, WARNING→NOTE). Supplied context
supports only bounded uncertainty, not confident false findings.
