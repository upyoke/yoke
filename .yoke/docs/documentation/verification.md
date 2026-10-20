# Documentation verification

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Documentation](index.md) > Verification
<!-- /yoke:breadcrumbs -->

Validate the complete teaching tree before publishing or refreshing its copies.
Run source commands from a claimed lane through `yoke dev run --lane <lane> --`.
Add new source pages to git before validation; snapshots use every present page.

## Check and publish

```text
python3 -m yoke_core.domain.documentation_render write --root docs/public
python3 -m yoke_core.domain.install_bundle_docs_validation check --root docs/public
python3 -m yoke_core.domain.documentation_residue --root <lane>
python3 -m yoke_core.domain.install_bundle_tree_sync sync --target-root <lane>
python3 -m yoke_core.domain.install_bundle_tree_sync check --target-root <lane>
```

Edit `nav.yaml` and authored pages, then regenerate their navigation. The corpus
check verifies the complete nav tree, links and fragments, current derived
blocks, privacy and the hard 350-line maximum after wrapping at 80 columns.
Pages above the advisory 20,000-character target need readability review;
that target alone does not refuse publication. Use the render `measure` command
for those review notes. Scenario checks still establish whether teaching works.
A project can cap a file's bytes with `file_byte_budget=PATH:BYTES` in
`.yoke/project.config`; `yoke check file-line --help` owns the rule.

Sync validates the complete source before writing anything. Its drift check
compares every installed and packaged file with source and measures generated
pages too. If a copy is stale, fix the source refusal first, then sync again;
editing the generated copy does not repair its owner. Bundle assembly validates
the served corpus, including gitless wheel/container snapshots, before delivery.
Successful validation is cached only for that root and its content digest.

## Refusals and review signals

Every refusal prints `CODE target: detail. Repair: ...`; commands exit 1 if any
refusal remains. Fix every named target and repeat the failed check.

| Code | Repair |
|---|---|
| `OVERSIZED_PAGE` | Split at meaningful topic boundaries and regenerate copies. |
| `PRIVATE_CONTENT` | Replace private material with portable placeholders and rebuild. |
| `STALE_GENERATED_COPY` | Sync from the validated source checkout. |
| `RETIRED_REFERENCE` | Cite the current concept-tree home and enforcing command. |
| `STALE_NAV_BLOCK` | Regenerate navigation blocks from the current tree. |
| `CORPUS_ROOT_MISSING` | Restore/select the named source checkout and README. |
| `CORPUS_READ_FAILED` | Restore readable git metadata and retry. |

The [navigation contract](navigation.md#named-navigation-refusals) owns nav and
link refusal details. Private content includes concrete personal home paths,
iCloud locations, machine-specific temporary captures and private identity
assignments. Explicit home placeholders, generic scratch-file recipes and
explicitly labeled schema/example identifiers are portable teaching; all-zero
identifier examples are synthetic.

The repository's `HC-doc-health` fails for public corpus defects, retired
references or copy drift. It recursively checks contributor Markdown links and
fragments, excluding archived records; those findings are `REVIEW` warnings,
not proof of a public publication failure. Address inaccurate teaching through
its actual owner. A warning never grants permission to ignore a required fix.

The retired-reference scan inspects tracked content, including test fixtures and
model records. It excludes historical archives, immutable Pack versions and
those same versions' packaged copies, historical release hashes, and pytest
timing data. Live Pack metadata, model records and consumer tests remain checked.
A kept filename at its current nested home is valid.

## Verify the exact candidate

Commit all served changes, then verify the declared full candidate and the
consumer's actual build evidence:

```text
python3 -m yoke_core.domain.install_bundle_docs_validation verify-candidate --root <lane> --commit <full-sha> --receipt <installed-receipt> --consumer-evidence <build-output>/yoke-docs-build-evidence.json
```

`--receipt` is optional when no installed receipt is being verified. The
[producer contract](navigation.md#consumer-build-evidence) owns the evidence
schema, location, identity rules and exact repairs for
`CANDIDATE_IDENTITY_MISMATCH` and `CONSUMER_PROOF_MISSING`. Verification compares
HEAD, clean served sources, receipt identity and both published copies against
the declared commit's source bytes. Missing proof never falls back to an older
corpus or ambient package metadata.

## Refresh an installed project

Run `yoke project refresh` after the release carrying these sources is installed.
The installer removes retired files whose bytes still have release/manifest
ownership proof. A locally modified file produces `install_drift_local_edits`
and preserves all files; save the edits outside installer-owned paths, restore
the recorded release bytes and rerun refresh. Interrupted applies retain their
staged candidate record; rerunning refresh recovers exact planned states.
