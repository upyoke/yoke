import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import {
  formatSessionControlTime,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
} from "./universe_session_control_data.js";

function relayCard(documentNode, relay) {
  const card = el(documentNode, "article", "panel session-relay-card");
  card.setAttribute("data-relay-id", String(relay.relay_id || ""));
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(
    documentNode, "h3", null, relay.hostname || relay.machine_id,
  ));
  const state = String(relay.liveness || "unknown");
  header.appendChild(el(
    documentNode, "span", `pill ${pillFamilyForState(state)}`, state,
  ));
  card.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  for (const [label, value] of [
    ["owner", relay.owner],
    ["machine", relay.machine_id],
    ["relay version", relay.relay_version],
    ["relay state", relay.state],
    ["last seen", formatSessionControlTime(relay.last_seen_at)],
    ["connected until", formatSessionControlTime(relay.connected_until)],
    ["projects", (relay.project_ids || []).join(", ")],
  ]) body.appendChild(el(documentNode, "p", "fact-line", `${label}: ${value || "—"}`));
  const versions = Object.entries(relay.surface_versions || {});
  if (versions.length) {
    body.appendChild(el(
      documentNode, "h4", "session-relay-surfaces-heading", "Supported surfaces",
    ));
    const list = el(documentNode, "ul", "session-relay-surfaces");
    for (const [surface, version] of versions) {
      list.appendChild(el(documentNode, "li", null, `${surface} ${version}`));
    }
    body.appendChild(list);
  } else {
    body.appendChild(el(
      documentNode,
      "p",
      "session-launch-guidance",
      "This relay advertises no launch surfaces.",
    ));
  }
  if (state !== "connected" || relay.state !== "active") {
    body.appendChild(el(
      documentNode,
      "p",
      "session-launch-guidance",
      "Launches and automatic wakes may be unavailable until this relay reconnects.",
    ));
  }
  card.appendChild(body);
  return card;
}

export function renderSessionRelaysView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const content = el(documentNode, "div", "session-relay-grid", "Loading relays…");
  main.replaceChildren(content);
  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Machine relays",
      summary: "Connected machines, supported surfaces, and heartbeat state.",
    });
  }
  const load = async () => {
    try {
      const projects = scopedProjectRefs(context, scope);
      const results = scope === "all"
        ? [await sessionControlCall(
          context, "session_control.relay.list", { limit: 500 },
        )]
        : await Promise.all(projects.map((project) => sessionControlCall(
          context, "session_control.relay.list", { project, limit: 500 },
        )));
      if (!context.isMounted()) return;
      const byRelay = new Map();
      for (const relay of results.flatMap((result) => result.relays || [])) {
        byRelay.set(String(relay.relay_id), relay);
      }
      content.replaceChildren();
      if (!byRelay.size) {
        content.appendChild(el(
          documentNode,
          "p",
          "sessions-empty",
          "No relay is visible. Connect a machine relay before launching or waking sessions.",
        ));
        return;
      }
      for (const relay of byRelay.values()) {
        content.appendChild(relayCard(documentNode, relay));
      }
    } catch (error) {
      renderSessionControlFailure(
        content, error, "Machine relays could not be loaded.",
      );
    }
  };
  load();
}
