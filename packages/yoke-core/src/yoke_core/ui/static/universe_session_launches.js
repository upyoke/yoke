import { el } from "./universe_view_support.js";
import { appendLaunchTimeline } from "./session_launch_timeline.js";
import { openSessionLaunchDialog } from "./session_launch_create_dialog.js";
import {
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

function appendAction(documentNode, actions, label, disabled, invoke) {
  const button = el(documentNode, "button", "item-button", label);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", () => invoke(button));
  actions.appendChild(button);
}

function launchCard(documentNode, launch, mutate) {
  const card = el(documentNode, "article", "panel session-launch-card");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(
    documentNode, "h3", null, launch.launch_id || "session launch",
  ));
  card.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line",
    `${launch.executor_surface || "unknown surface"} · ${launch.machine_id || "unassigned"}`,
  ));
  appendLaunchTimeline(documentNode, body, launch);
  if (launch.registered_session_id) {
    const link = el(
      documentNode, "a", "session-result-link", launch.registered_session_id,
    );
    link.href = "#/sessions/roster";
    body.appendChild(link);
  }
  if (RECONCILE_FIRST_STATES.has(launch.state)) {
    body.appendChild(el(
      documentNode,
      "p",
      "session-launch-guidance",
      "Native session creation is uncertain. Reconcile whether a session exists before retrying or creating another one.",
    ));
  }
  const actions = el(documentNode, "div", "session-control-actions");
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
      summary: "Exact-surface eligibility, launch progress, retry, and cancellation.",
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
  const mutate = async (operation, launchId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = `${operation === "retry" ? "Retrying" : "Cancelling"} ${launchId}…`;
    try {
      await sessionControlCall(
        context, `session_control.launch.${operation}`, { launch_id: launchId },
      );
      status.textContent = `${launchId} ${operation === "retry" ? "retried" : "cancelled"}.`;
      await load();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, `The launch could not be ${operation === "retry" ? "retried" : "cancelled"}.`,
      );
      button.disabled = false;
    }
  };
  create.addEventListener("click", async () => {
    try {
      await openSessionLaunchDialog(context, dialogHost, projects, load);
    } catch (error) {
      status.hidden = false;
      status.textContent = presentSessionControlFailure(
        error, "The launch dialog could not be opened.",
      );
    }
  });
  load();
}
