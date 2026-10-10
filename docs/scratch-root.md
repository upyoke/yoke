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

1. Effective configured root: nonempty `YOKE_SCRATCH_ROOT`, otherwise
   `~/.yoke/config.json:temp_root`.
2. OS-temp `yoke-scratch/` fallback. On macOS, `/tmp` is preferred over
   a per-process `/var/folders/...` temp base when `/tmp` exists.

Relative env or config values resolve from the machine-local Yoke directory. Empty env or
machine-config values are ignored. An unwritable effective root warns and
falls back to OS temp; a bad env override does not retry the config root. `ScratchRootResolutionError`
is reserved for the case where the OS temp fallback is also unavailable.

`global_scratch_root() -> Path` returns the configured/env/fallback root
without the project segment. It is only for cross-project artifacts that must
have one location across execution contexts, such as the disposable Postgres
test cluster.

Project namespacing is resolved from an explicit project argument, a process
override, or the current checkout's machine-config project entry (the env-scoped
checkout→project list resolves the row whose env matches the active/requested
env, since project ids are numbered per universe). Repo config keys do not
define project context. Connected references resolve to numeric project ids;
offline callers retain an explicit safe slug. Missing/unresolvable projects
refuse rather than choosing an unrelated namespace.

## Accessors

All accessors return absolute `Path` objects.

`scratch_root(project=None, *, session_segment=None) -> Path`
: Resolved project/session/run scratch root, always
`<global_scratch_root>/<project>/sessions/<session>/runs/<run>`.
`session_segment` lets a caller that already resolved and vetted the session
namespace supply it instead of resolving ambient identity a second time.

`dispatch_inputs_dir(project=None, public_ref=None, session_id=None, attempt=None, *, create=True) -> Path`
: `<scratch_root(project)>/dispatch-inputs`. Supply all three dispatch fields
  together to add `PREFIX-N/<session>/attempt-<n>`; partial fields refuse.

`hook_marker_path(name, project=None, *, create_parent=True) -> Path`
: Marker file path under `<global_scratch_root>/<project>/hook-markers/`.

`harness_runtime_cache_path(name, project=None, *, create_parent=True) -> Path`
: Harness cache file path under `<global_scratch_root>/<project>/harness-runtime-cache/`.

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

Hook markers and harness caches are project-stable: session/run segments
would prevent sibling hook processes from sharing coordination state. Other
accessors above use session/run namespaces. Names are safe single path
segments; absolute paths and parent traversal refuse. Run identity uses
`YOKE_RUN_ID`, `YOKE_EXECUTION_ID`, `GITHUB_RUN_ID`, then `pid-<process>`.

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

With that root, connected project scratch is
`/tmp/yoke-scratch/<project-id>/sessions/<session>/runs/<run>/`; project-stable
coordination sits directly under `<project-id>/`. Shared test clusters use the
global root without a project/session/run namespace.

## Relocation Doctrine

Callers should ask this helper for scratch paths instead of assembling
`/tmp/yoke-*`, `tempfile.gettempdir()`, or dispatch-input directories
paths inline. Cloud or multi-host relocation should change the helper's
resolution rule or the operator-provided root; it should not require another
caller inventory.
