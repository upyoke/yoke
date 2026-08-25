# Machine Temp Scratch Paths

`yoke_core.domain.project_scratch_dir` is the shared helper for
Yoke-owned scratch files. It keeps transient filesystem writes behind one
machine temp root so operators can rebind local scratch storage without
editing every caller. Two modules own the pieces it composes:
`project_scratch_roots` resolves and proves the writable root, and
`project_scratch_segments` owns the session and run namespaces layered on
top of it.

## Resolution Order

The helper returns absolute, writable paths.
Resolution is:

1. `YOKE_SCRATCH_ROOT`
2. `~/.yoke/config.json:temp_root`
3. `{TMPDIR}/yoke-scratch/`

Relative env or config values resolve from the machine-local Yoke directory. Empty env or
machine-config values are ignored. If an env or config root cannot be created or
written, the helper emits a warning and falls back. `ScratchRootResolutionError`
is reserved for the case where the OS temp fallback is also unavailable.

`global_scratch_root() -> Path` returns the configured/env/fallback root
without the project segment. It is only for cross-project artifacts that must
have one location across execution contexts, such as the disposable Postgres
test cluster.

Project namespacing is resolved from an explicit project argument, a process
override, or the current checkout's machine-config project entry (the env-scoped
checkout→project list resolves the row whose env matches the active/requested
env, since project ids are numbered per universe). Repo config keys do not
define project context.

## Accessors

All accessors return absolute `Path` objects.

`scratch_root(project=None, *, session_segment=None) -> Path`
: Resolved project/session/run scratch root, always
`<global_scratch_root>/<project>/sessions/<session>/runs/<run>`.
`session_segment` lets a caller that already resolved and vetted the session
namespace supply it instead of resolving ambient identity a second time.

`dispatch_inputs_dir(project=None, *, create=True) -> Path`
: Dispatch prompt input directory under `<scratch_root(project)>/dispatch-inputs`.

`hook_marker_path(name, project=None, *, create_parent=True) -> Path`
: Marker file path under `<scratch_root(project)>/hook-markers/`.

`harness_runtime_cache_path(name, project=None, *, create_parent=True) -> Path`
: Harness cache file path under `<scratch_root(project)>/harness-runtime-cache/`.

`watcher_capture_path(command, stream, nonce=None, project=None, *, suffix=".log", create_parent=True) -> Path`
: Watcher capture file path under `<scratch_root(project)>/watcher-captures/`.
Raises `ScratchSessionIdentityError` inside a harness session whose ambient
identity does not resolve, rather than minting under the `session-unknown`
placeholder — the session-cwd guard admits a capture only when its session
segment matches the calling session, so that path is refused on the next tool
call, naming the path instead of the identity gap that produced it. An
operator's own terminal is legitimately session-less and keeps the placeholder.

`mint_watcher_capture_pair(command, project=None) -> tuple[Path, Path]`
: Returns raw and progress capture paths that share one nonce. Same refusal.

`ephemeral_payload(prefix="payload", suffix="", project=None, *, delete=True) -> Iterator[Path]`
: Context manager that creates a temporary payload file under
`<scratch_root(project)>/payloads/` and deletes it on exit unless
`delete=False`.

`scratch_subdir(prefix="scratch", project=None, *, delete=True) -> Iterator[Path]`
: Context manager that creates a temporary directory under
`<scratch_root(project)>/scratch-dirs/` and removes it on exit unless
`delete=False`.

`storage_path(kind, *parts, project=None, create_parent=True) -> Path`
: Durable scratch-storage path under `<scratch_root(project)>/storage/<kind>/`.

## Operator Rebinding

Use `YOKE_SCRATCH_ROOT` for a per-process override:

```bash
YOKE_SCRATCH_ROOT=/fast/local/yoke-scratch yoke watch pytest -- runtime/api/
```

Use machine config for a per-installation default:

```json
{
  "temp_root": "/tmp/yoke-scratch"
}
```

With `temp_root=/tmp/yoke-scratch`, Yoke project scratch lands under
`/tmp/yoke-scratch/yoke/`, while the shared local test cluster lands under
`/tmp/yoke-scratch/yoke-pgtest-cluster/`.

## Relocation Doctrine

Callers should ask this helper for scratch paths instead of assembling
`/tmp/yoke-*`, `tempfile.gettempdir()`, or dispatch-input directories
paths inline. Cloud or multi-host relocation should change the helper's
resolution rule or the operator-provided root; it should not require another
caller inventory.
