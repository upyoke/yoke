import { el } from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { appendLaunchTimeline } from "./session_launch_timeline.js";
import { openSessionLaunchDialog } from "./session_launch_create_dialog.js";
import { appendRelayDiagnostic } from "./session_relay_diagnostic_view.js";
import {
  displaySessionModel,
  sessionModelFactTags,
} from "./session_model_display.js";
import {
  labelledControl,
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";

const RETRYABLE_STATES = new Set(["failed", "expired"]);
const RECONCILE_FIRST_STATES = new Set(["outcome_unknown"]);
const CANCELLABLE_STATES = new Set([
  "queued", "assigned", "launching", "awaiting_registration",
]);
const RESULT_EVIDENCE_FIELDS = Object.freeze([
  ["adapter_revision", "text"],
  ["native_instruction_sha256", "text"],
  ["result_code", "text"],
  ["probe_detail", "text"],
  ["surface", "text"],
  ["duration_ms", "integer"],
  ["exit_code", "integer"],
]);

export function launchIdentityPresentation(launch) {
  const nativeSessionId = String(launch.native_session_id || "").trim();
  const registeredSessionId = String(launch.registered_session_id || "").trim();
  const state = String(launch.identity_correlation || "unknown");
  const result = String(launch.result_code || "unknown").replaceAll("_", " ");
  const labels = {
    matched: "Identity matched",
    mismatch: "Identity mismatch: native and registered sessions differ",
    awaiting_registration: "Awaiting registration",
    registration_failed: "Session registration failed",
    native_unreported: "Registered; native identity not reported",
    correlation_failed: `Identity correlation failed: ${result}`,
    unavailable: "Native identity unavailable",
    pending: "Waiting for native session",
    unknown: "Identity correlation status unavailable",
  };
  return {
    state: state.replaceAll("_", "-"),
    label: labels[state] || state.replaceAll("_", " "),
    nativeSessionId: nativeSessionId || null,
    registeredSessionId: registeredSessionId || null,
  };
}

function instructionDeliveryPresentation(launch) {
  const state = String(launch.instruction_delivery || "unknown");
  const labels = {
    delivered: "Launch instruction delivered",
    not_delivered: "Launch instruction not delivered",
    pending: "Launch instruction delivery pending",
    unknown: "Launch instruction delivery status unavailable",
  };
  return { state: state.replaceAll("_", "-"), label: labels[state] || state };
}

function appendLaunchIdentity(documentNode, body, launch) {
  const identity = launchIdentityPresentation(launch);
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-launch-identity",
    `Launch ${launch.launch_id || "unreported"} → native ${identity.nativeSessionId || "pending"} → registered ${identity.registeredSessionId || "pending"}`,
  ));
  body.appendChild(el(
    documentNode,
    "p",
    `session-launch-correlation ${identity.state}`,
    identity.label,
  ));
  const delivery = instructionDeliveryPresentation(launch);
  body.appendChild(el(
    documentNode,
    "p",
    `session-launch-delivery ${delivery.state}`,
    delivery.label,
  ));
  const evidence = launch.result_evidence;
  if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) return;
  const facts = [];
  for (const [key, kind] of RESULT_EVIDENCE_FIELDS) {
    const value = evidence[key];
    if (kind === "text" && typeof value === "string" && value.trim()) {
      facts.push(`${key.replaceAll("_", " ")}: ${value.trim().slice(0, 128)}`);
    } else if (kind === "integer" && Number.isInteger(value)) {
      facts.push(`${key.replaceAll("_", " ")}: ${value}`);
    }
  }
  if (facts.length) {
    body.appendChild(el(
      documentNode,
      "p",
      "fact-line session-launch-result-evidence",
      `Result evidence · ${facts.join(" · ")}`,
    ));
  }
  appendRelayDiagnostic(
    documentNode, body, evidence, launch.assigned_machine_id,
  );
}

function appendAction(documentNode, actions, label, disabled, invoke) {
  const button = el(documentNode, "button", "item-button", label);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", () => invoke(button));
  actions.appendChild(button);
}

function selectionLabels(row, emptyModel) {
  return [
    displaySessionModel(row, emptyModel),
    ...sessionModelFactTags(row).map((fact) => fact.label),
  ];
}

function launchCard(documentNode, launch, mutate) {
  const card = el(documentNode, "article", "panel session-launch-card");
  card.setAttribute("data-launch-id", String(launch.launch_id || ""));
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(
    documentNode, "h3", null, "Session launch",
  ));
  card.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(el(
    documentNode, "code", "session-control-id", launch.launch_id || "—",
  ));
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line",
    `${launch.requested_surface || "unknown surface"} requested · ${launch.selected_surface || "unselected"} selected · ${launch.assigned_machine_id || "unassigned"}`,
  ));
  const explicitSelection = selectionLabels(launch, "vendor defaults requested");
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-launch-model-request",
    `Explicit request · ${explicitSelection.join(" · ")}`,
  ));
  const effectiveSelection = selectionLabels({
    model: launch.resolved_model,
    reasoning_effort: launch.resolved_reasoning_effort,
    context_window_tokens: launch.resolved_context_window_tokens,
  }, "vendor model default");
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-launch-model-selection",
    `Effective launch selection · ${effectiveSelection.join(" · ")}`,
  ));
  if (
    launch.selected_surface
    && launch.selected_surface !== launch.requested_surface
  ) {
    body.appendChild(el(
      documentNode, "p", "session-launch-guidance", "Same-family fallback used.",
    ));
  }
  appendLaunchTimeline(documentNode, body, launch);
  appendLaunchIdentity(documentNode, body, launch);
  if (launch.registered_session_id) {
    const link = el(
      documentNode,
      "a",
      "session-result-link",
      `Open registered session ${launch.registered_session_id}`,
    );
    link.href = buildUniverseRoute(
      "sessions",
      launch.project_id == null ? null : String(launch.project_id),
      String(launch.registered_session_id),
    );
    body.appendChild(link);
  }
  const actions = el(documentNode, "div", "session-control-actions");
  if (RECONCILE_FIRST_STATES.has(launch.state)) {
    body.appendChild(el(
      documentNode,
      "p",
      "session-launch-guidance",
      "The launch instruction was not delivered. Reconcile whether a native session exists before retrying or creating another one.",
    ));
    const observedNativeId = el(
      documentNode, "input", "session-control-input session-launch-reconcile-id",
    );
    observedNativeId.type = "text";
    observedNativeId.placeholder = "Leave blank only if no native session was created";
    body.appendChild(labelledControl(
      documentNode,
      "Observed native session ID (optional)",
      observedNativeId,
    ));
    const reconcile = el(documentNode, "button", "item-button", "Reconcile");
    reconcile.type = "button";
    reconcile.addEventListener("click", () => {
      const nativeId = String(observedNativeId.value || "").trim();
      mutate("reconcile", launch.launch_id, reconcile, nativeId
        ? { observed_native_id: nativeId }
        : {});
    });
    actions.appendChild(reconcile);
  } else if (RETRYABLE_STATES.has(launch.state)) {
    body.appendChild(el(
      documentNode,
      "p",
      "session-launch-guidance",
      "This attempt stopped before registration. Retry starts a new attempt with the same exact request.",
    ));
  }
  appendAction(
    documentNode, actions, "Cancel",
    !CANCELLABLE_STATES.has(launch.state),
    (button) => mutate("cancel", launch.launch_id, button),
  );
  appendAction(
    documentNode, actions, "Retry",
    !RETRYABLE_STATES.has(launch.state),
    (button) => mutate("retry", launch.launch_id, button),
  );
  body.appendChild(actions);
  card.appendChild(body);
  return card;
}

function renderLaunches(documentNode, host, launches, mutate) {
  host.replaceChildren();
  if (!launches.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", "No session launches yet."));
    return;
  }
  const grid = el(documentNode, "div", "session-launch-grid");
  for (const launch of launches) grid.appendChild(launchCard(documentNode, launch, mutate));
  host.appendChild(grid);
}

export function renderSessionLaunchesView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = scopedProjectRefs(context, scope);
  const view = el(documentNode, "div", "session-control-view");
  const status = statusRegion(documentNode);
  const content = el(documentNode, "div", "session-control-content", "Loading launches…");
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  const create = el(documentNode, "button", "item-button", "Create session");
  create.type = "button";
  create.disabled = projects.length === 0;
  const actions = el(documentNode, "div", "session-control-actions");
  actions.appendChild(create);
  view.appendChild(actions);
  view.appendChild(status);
  view.appendChild(content);
  view.appendChild(dialogHost);
  main.replaceChildren(view);
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Session launches",
      summary: "Explicit surface selection, launch progress, retry, and cancellation.",
      actions: [create],
    });
  }
  const load = async () => {
    try {
      const results = await Promise.all(projects.map((project) => (
        sessionControlCall(context, "session_control.launch.list", {
          project, limit: 100,
        })
      )));
      if (!context.isMounted()) return;
      const launches = results.flatMap((result) => result.launches || []);
      renderLaunches(documentNode, content, launches, mutate);
    } catch (error) {
      renderSessionControlFailure(
        content, error, "Session launches could not be loaded.",
      );
    }
  };
  const mutate = async (operation, launchId, button, extraPayload = {}) => {
    button.disabled = true;
    status.hidden = false;
    const progress = {
      cancel: "Cancelling", reconcile: "Reconciling", retry: "Retrying",
    };
    status.textContent = `${progress[operation]} ${launchId}…`;
    try {
      await sessionControlCall(
        context,
        `session_control.launch.${operation}`,
        { launch_id: launchId, ...extraPayload },
      );
      const completed = {
        cancel: "cancelled", reconcile: "reconciled", retry: "retried",
      };
      status.textContent = `${launchId} ${completed[operation]}.`;
      await load();
    } catch (error) {
      const failureAction = {
        cancel: "cancelled", reconcile: "reconciled", retry: "retried",
      };
      status.textContent = presentSessionControlFailure(
        error, `The launch could not be ${failureAction[operation]}.`,
      );
      button.disabled = false;
    }
  };
  const launchCreated = async (result) => {
    const launchId = result?.launch?.launch_id || "Session launch";
    status.hidden = false;
    status.textContent = `${launchId} created. Tracking registration below.`;
    await load();
  };
  create.addEventListener("click", async () => {
    try {
      await openSessionLaunchDialog(context, dialogHost, projects, launchCreated);
    } catch (error) {
      status.hidden = false;
      status.textContent = presentSessionControlFailure(
        error, "The launch dialog could not be opened.",
      );
    }
  });
  load();
}
