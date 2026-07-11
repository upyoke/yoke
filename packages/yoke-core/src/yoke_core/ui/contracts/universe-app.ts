/**
 * Public, host-neutral contract for the wheel-shipped universe app.
 *
 * This is declaration-emitting TypeScript source, not a separately
 * published package. A host consumes it from the same pinned Yoke product
 * version whose static app bundle it serves.
 */

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | readonly JsonValue[];
export interface JsonObject {
  readonly [key: string]: JsonValue;
}

export type FunctionTargetKind =
  | "item"
  | "epic_task"
  | "section"
  | "claim"
  | "db_claim"
  | "path_claim"
  | "project_structure"
  | "qa_requirement"
  | "workflow_run"
  | "global";

export interface FunctionTarget {
  readonly kind: FunctionTargetKind;
  readonly item_id?: number;
  readonly item_ref?: string;
  readonly epic_id?: number;
  readonly task_num?: number;
  readonly section_name?: string;
  readonly claim_id?: number;
  readonly path_claim_id?: number;
  readonly db_claim_id?: number;
  readonly project_id?: string;
  readonly qa_requirement_id?: number;
  readonly workflow_run_id?: string;
}

export interface FunctionCallRequest<Payload extends JsonObject = JsonObject> {
  readonly function: string;
  readonly payload?: Payload;
  readonly target?: FunctionTarget;
  readonly request_id?: string;
  readonly options?: JsonObject;
}

export interface FunctionWarning {
  readonly code: string;
  readonly step: string;
  readonly detail: string;
  readonly recovery_function?: string | null;
}

export interface FunctionError {
  readonly code?: string;
  readonly message: string;
  readonly jsonpath?: string | null;
  readonly recovery_hint?: string | null;
}

export interface FunctionEnvelope<Result = JsonObject> {
  /** Absent on transport-level proxy refusals; truthy only for success. */
  readonly success?: boolean;
  readonly function?: string;
  readonly version?: string;
  readonly request_id?: string | null;
  readonly result?: Result;
  readonly warnings?: readonly FunctionWarning[];
  readonly error?: FunctionError | null;
  readonly event_ids?: readonly number[];
}

export interface FunctionCallResult<Result = JsonObject> {
  readonly status: number;
  readonly envelope: FunctionEnvelope<Result>;
}

export interface UniverseFunctionClient {
  call<Result = JsonObject, Payload extends JsonObject = JsonObject>(
    request: FunctionCallRequest<Payload>,
  ): Promise<FunctionCallResult<Result>>;
}

export interface HttpFunctionClientOptions {
  /** Defaults to the local, same-origin `/api/functions/call` route. */
  readonly endpoint?: string;
  readonly fetch?: (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>;
}

export interface UniverseActionOption {
  readonly id: string;
  readonly label: string;
  readonly data?: unknown;
}

/** A generic data-driven action; its meaning remains host-owned. */
export interface UniverseAction {
  readonly label: string;
  readonly options?: readonly UniverseActionOption[];
  readonly onInvoke: (
    option?: UniverseActionOption,
  ) => void | Promise<void>;
}

/**
 * Opaque host capability data. Capability presence and string flags carry
 * state without coupling the app to a bag of host-specific booleans.
 */
export interface UniverseCapabilities {
  readonly flags?: readonly string[];
  readonly data?: Readonly<Record<string, unknown>>;
  readonly actions?: readonly UniverseAction[];
}

/**
 * Slot nodes are host-owned. Mount moves each supplied node into the app;
 * unmount detaches it, leaving the original node reference reusable.
 */
export type UniverseSlotContent =
  | Element
  | (() => Element | null | undefined);

export interface UniverseAppSlots {
  readonly topbarStart?: UniverseSlotContent;
  readonly topbarEnd?: UniverseSlotContent;
  readonly navigationStart?: UniverseSlotContent;
  readonly navigationEnd?: UniverseSlotContent;
  readonly contentBefore?: UniverseSlotContent;
  readonly contentAfter?: UniverseSlotContent;
}

export interface UniverseAppOptions {
  readonly client?: UniverseFunctionClient;
  readonly capabilities?: UniverseCapabilities;
  readonly slots?: UniverseAppSlots;
}

export interface UniverseAppMount {
  readonly contractVersion: typeof UNIVERSE_APP_CONTRACT_VERSION;
  unmount(): void;
}

export type UniverseRouteView = "items" | "strategy";

export interface UniverseRoute {
  readonly view: UniverseRouteView;
  readonly project: string | null;
}

/** Canonical value; the runtime module is emitted from this source. */
export const UNIVERSE_APP_CONTRACT_VERSION = 1 as const;

export declare function createHttpFunctionClient(
  options?: HttpFunctionClientOptions,
): UniverseFunctionClient;

export declare function parseUniverseRoute(hash: string): UniverseRoute;

export declare function buildUniverseRoute(
  view: UniverseRouteView | string,
  project?: string | null,
): string;

export declare function mountUniverseApp(
  rootNode: HTMLElement,
  options?: UniverseAppOptions,
): UniverseAppMount;
