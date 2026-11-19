# CI image mirrors

CI uses public `ghcr.io/upyoke/postgres:16`, `ghcr.io/upyoke/registry:2`,
`ghcr.io/upyoke/python:3.13-slim`, and `ghcr.io/upyoke/buildkit:v0.34.2`. The
Python mirror also supplies the root Dockerfile; the buildkit mirror is the
Buildx `docker-container` driver image, so Buildx setup never pulls from Docker
Hub. Consumers need no registry credentials.

The [ci-image-mirror workflow](../.github/workflows/ci-image-mirror.yml) copies
each image from the upstream source its matrix entry names (Docker Official
Images from `docker.io/library`, buildkit from `docker.io/moby`) daily at
04:37 UTC, on changes
to itself, and on manual dispatch. Its repository-scoped `GITHUB_TOKEN` has
only `packages: write`; no AWS credentials or personal token are needed.
Forks skip publication to upyoke. Skopeo copies every upstream platform and
preserves manifest digests, then verifies the public index and both Linux
amd64 and arm64 image configurations without credentials.

Each stable tag moves only when its complete multi-platform copy succeeds.
A failed refresh leaves the last successfully published image available;
consumers do not depend on the refresh workflow's conclusion. Postgres tracks
the upstream 16.x line, registry tracks 2, and Python tracks 3.13-slim.
Buildkit is pinned to one release (`v0.34.2`, the `buildx-stable-1` release
when mirrored); move it by changing the tag in the mirror matrix and in every
`driver-opts` consumer together.

## First publication and public visibility

Publish the mirror workflow on the candidate branch before switching CI
consumers. Its push trigger seeds every package. New GHCR packages are
private by default, even when published by a public repository.

GitHub exposes the visibility change in package settings; its package REST
API does not expose a visibility mutation. This one-time setting requires an
upyoke package administrator. Escalate it to the operator rather than claiming
that a successful authenticated upload makes a public package.

For each package, open Package settings, then Change visibility, select
Public, and confirm the package name:

- [postgres settings](https://github.com/orgs/upyoke/packages/container/postgres/settings)
- [registry settings](https://github.com/orgs/upyoke/packages/container/registry/settings)
- [python settings](https://github.com/orgs/upyoke/packages/container/python/settings)
- [buildkit settings](https://github.com/orgs/upyoke/packages/container/buildkit/settings)

These packages contain unchanged public upstream images. The intended Public
visibility is declared here and enforced on every refresh by anonymous reads.
The publishing repository is linked automatically by `GITHUB_TOKEN`; consumer
repositories require no package access grants.

After setting visibility, rerun the failed mirror run from Actions. Switch
consumer references only after every copy job passes. After landing, the
daily schedule and manual dispatch operate from the default branch.

## Failure recovery and evidence

`CI-MIRROR-TOOL-INSTALL` means Ubuntu could not provide Skopeo; check package
availability and rerun. `CI-MIRROR-REFRESH` names the image whose copy or
platform verification failed; inspect that step's registry response, fix the
reported upstream or GHCR access problem, and rerun. `CI-MIRROR-NOT-PUBLIC`
requires the administrator visibility step above. `CI-MIRROR-DIGEST-MISMATCH`
requires another refresh and investigation of concurrent registry writers.
The workflow serializes refresh runs to avoid tag races.

The Actions run retains copy output, diagnosed errors, and per-image summaries
with the copied/public digest and platform verification. Do not accept upload
alone as bootstrap proof. Completion also requires the full CI run on the
consumer candidate to pass without ECR pulls.

References: [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility),
and [Skopeo copy semantics](https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md).
