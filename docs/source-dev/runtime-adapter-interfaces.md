# Runtime adapter interfaces

Core domain code imports shared values and helpers from `yoke_contracts`.
Machine effects that belong to the CLI or a harness are supplied through
structural interfaces in `yoke_contracts.runtime_ports`. Each interface names
the operations or values its callers consume, without importing an adapter.

The implementation package publishes one standard Python entry point in the
`yoke.runtime` group for each interface it implements. The interface accessor
loads that entry point, checks that every declared member exists, and retains
the implementation's identity. Existing exception classes, callbacks, context
managers and process-local state remain owned by their implementations.

There is no registration command or environment switch. Local, self-hosted and
hosted installs use the same package metadata and resolution path. A missing,
duplicate, unloadable or incomplete implementation refuses with
`runtime_adapter_unavailable` and names the interface and repair. Install
matching packages with the official installer; source contributors sync the
checkout's locked environment. No alternate implementation is guessed.

Bootstrap code runs before package metadata exists. It uses shared helpers
directly, including `yoke_contracts.resilient_fetch` for artifact downloads;
it never resolves a runtime interface. The Postgres bootstrap test exercises
this boundary with `python -S` and only core and contracts on the source path.

When adding an operation, extend the owning interface and its adapter in the
same change. Keep pure records and helpers in shared contracts. Tests may
supply a structural implementation without importing a CLI or harness package;
the installed metadata remains the runtime composition authority.

Source analysis reads the checkout's entry-point declarations without loading
installed adapters. Hook-policy reachability follows referenced provider members,
and impacted-test selection follows provider-to-interface dependencies. These
runtime implementation relationships remain distinct from direct Python imports
used by architecture boundary checks.

Core function calls use the `structured_dispatch` interface. Its service API
provider owns transport selection, in-process dispatch and version-skew recovery;
domain callers depend on the request/response contract and never import the
service client or CLI transport. Actor envelopes and response emission cross the
same interface. Current session lookup and item projection field sets are domain
vocabulary and remain available directly from their domain owners.
