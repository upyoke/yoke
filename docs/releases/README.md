# Yoke release notes

This directory is the authored source for public GitHub Release notes. It
starts at the first release made through the current release factory; older
tags are deliberately not backfilled with reconstructed history.

## Cut a release

1. Choose the next version `X.Y.Z+local.N` and add a matching
   `docs/releases/vX.Y.Z+local.N.md` on `main`. The PEP 440 local segment is
   intentional: public indexes cannot publish local versions, which keeps a
   same-named public package from satisfying Yoke's exact sibling pins. Use a
   short lowercase label such as `build.1`; the file must be nonempty and
   begin with `# Yoke X.Y.Z+local.N`. Write for operators and users: name
   visible changes, upgrade steps, and compatibility breaks. Do not paste
   ticket chronology or internal planning provenance.
2. Run the canonical test gate on that exact commit and merge it to `main`.
3. Create an annotated `vX.Y.Z+local.N` tag at the verified main commit and
   push only that tag. The `yoke-release` workflow refuses tags without the
   required local segment, commits not reachable from `main`,
   missing/mismatched notes, or a wheel version that differs from the tag.
4. The workflow calls `yoke-build-artifacts`, which builds and validates the
   four product wheels, signs GitHub build-provenance attestations for those
   exact wheel bytes, and uploads the release tree. Only after those checks
   pass does the final job create the GitHub Release with the wheels,
   `release-records.json`, and the authored note.

A new note can start from this shape:

```markdown
# Yoke X.Y.Z+local.N

## Highlights

Describe the user-visible outcome.

## Upgrade notes

State required actions, or say that the normal update path is sufficient.

## Compatibility

Name API, server/CLI, schema, or self-host compatibility changes. Say `None`
when there are none.
```

The SHA12 server image is a separate, repository-variable-gated factory lane.
For the same release commit, arm `YOKE_PUBLISH_SERVER_IMAGE` only when image
publication is intended, then run `yoke-server-image` on that commit. One
build pushes both `:<sha12>` and (from `main`) `:latest`; the provenance
attestation names the repository without a tag and binds the exact immutable
image digest.

## Verify provenance

Download a wheel from the GitHub Release, then verify both its bytes and the
GitHub-hosted signer workflow:

```bash
gh attestation verify ./yoke_core-*.whl \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-build-artifacts.yml \
  --deny-self-hosted-runners
```

Resolve or copy the immutable image digest from the completed image workflow,
authenticate Docker to GHCR, and verify that digest rather than `latest`:

```bash
docker login ghcr.io
gh attestation verify \
  oci://ghcr.io/upyoke/yoke-server@sha256:<digest> \
  --repo upyoke/yoke \
  --signer-workflow upyoke/yoke/.github/workflows/yoke-server-image.yml \
  --deny-self-hosted-runners
```

The wheel manifest and package-index hashes remain useful transport-integrity
checks. The GitHub attestations add the authenticated claim tying those bytes
to this repository, source commit, workflow, and GitHub-hosted build identity.
