import { el } from "./universe_view_support.js";

function input(documentNode, label, kind = "text") {
  const wrapper = el(documentNode, "label", "session-roster-filter");
  wrapper.appendChild(el(documentNode, "span", null, label));
  const control = el(documentNode, kind === "select" ? "select" : "input");
  wrapper.appendChild(control);
  return { wrapper, control };
}

function option(documentNode, value, label) {
  const node = el(documentNode, "option", null, label);
  node.value = value;
  return node;
}

function includes(value, query) {
  return !query || String(value || "").toLowerCase().includes(query);
}

const DEFAULT_STATE = "active";

export function sessionRosterFilters(documentNode, onChange) {
  const host = el(documentNode, "div", "session-roster-filters");
  host.setAttribute("role", "search");
  host.setAttribute("aria-label", "Filter sessions");
  const controls = {};
  for (const [name, label] of [
    ["search", "Search"], ["harness", "Harness"], ["machine", "Machine"],
  ]) {
    const field = input(documentNode, label);
    field.control.placeholder = name === "search"
      ? "Session, item, model, or operator"
      : `Filter by ${label.toLowerCase()}`;
    controls[name] = field.control;
    host.appendChild(field.wrapper);
  }
  const state = input(documentNode, "State", "select");
  for (const [value, label] of [
    ["", "Any state"], ["active", "Active"], ["stale", "Stale"], ["ended", "Ended"],
  ]) {
    state.control.appendChild(option(documentNode, value, label));
  }
  state.control.value = DEFAULT_STATE;
  controls.state = state.control;
  host.appendChild(state.wrapper);
  const clear = el(documentNode, "button", "item-button session-filter-clear", "Clear filters");
  clear.type = "button";
  clear.disabled = true;
  const hasChanges = () => String(controls.search.value || "").trim()
    || String(controls.harness.value || "").trim()
    || String(controls.machine.value || "").trim()
    || controls.state.value !== DEFAULT_STATE;
  const changed = () => {
    clear.disabled = !hasChanges();
    onChange();
  };
  for (const control of Object.values(controls)) {
    control.addEventListener("input", changed);
    control.addEventListener("change", changed);
  }
  clear.addEventListener("click", () => {
    controls.search.value = "";
    controls.harness.value = "";
    controls.machine.value = "";
    controls.state.value = DEFAULT_STATE;
    changed();
  });
  host.appendChild(clear);
  return {
    host,
    isRestrictive() {
      return Boolean(
        String(controls.search.value || "").trim()
        || String(controls.harness.value || "").trim()
        || String(controls.machine.value || "").trim()
        || controls.state.value,
      );
    },
    summary() {
      const values = [`State: ${controls.state.value || "any"}`];
      for (const [key, label] of [
        ["search", "Search"], ["harness", "Harness"], ["machine", "Machine"],
      ]) {
        const value = String(controls[key].value || "").trim();
        if (value) values.push(`${label}: ${value}`);
      }
      return values;
    },
    apply(rows) {
      const query = String(controls.search.value || "").toLowerCase();
      const harness = String(controls.harness.value || "").toLowerCase();
      return rows.filter((row) => {
        const searchable = [
          row.session_id, row.project, row.focus, row.actor_label,
          row.current_item_title, row.model,
        ].join(" ").toLowerCase();
        return (!query || searchable.includes(query))
          && (!harness || includes(row.executor, harness)
            || includes(row.executor_surface, harness))
          && (
            includes(row.machine_id, String(controls.machine.value || "").toLowerCase())
            || includes(row.machine_name, String(controls.machine.value || "").toLowerCase())
          )
          && (!controls.state.value || row.liveness === controls.state.value);
      });
    },
  };
}

function machineLabel(row) {
  return row.machine_name || row.machine_id || "machine not reported";
}

// One line, one fact: whether this session's machine is reachable right now.
// The relay is what carries a message to a session that is not mid-turn, so
// its state is the whole difference between reaching the session and queuing
// for it indefinitely.
function appendRelay(documentNode, body, row) {
  const line = el(documentNode, "div", "session-relay");
  line.appendChild(el(documentNode, "span", "session-relay-label", "Relay:"));
  const connected = row.relay === "connected";
  const pill = el(
    documentNode,
    "span",
    `pill ${connected ? "good" : "crit"} session-relay-pill`,
  );
  pill.appendChild(el(
    documentNode, "span", "session-relay-machine", machineLabel(row),
  ));
  pill.setAttribute("data-state", connected ? "connected" : "unavailable");
  pill.title = machineLabel(row);
  line.appendChild(pill);
  if (!connected) {
    line.appendChild(el(
      documentNode,
      "span",
      "session-relay-warning",
      "no relay connected",
    ));
  }
  body.appendChild(line);
}

// Whether a message sent from this card would actually arrive, and — when it
// would not — the single condition standing in the way. Delivery needs a
// surface whose hook can carry the message, and, for a session that is not
// mid-turn, a wake route to make that surface run; the relay is what carries
// the wake.
export function messagingAvailability(row) {
  const routing = row.messageability || {};
  if (routing.reason === "session_terminated") {
    return {
      available: false,
      reason: "Messaging unavailable: this session was terminated.",
    };
  }
  if (routing.messageable !== true) {
    if (routing.reason === "version_below_floor_or_unknown") {
      return {
        available: false,
        reason: routing.minimum_version
          ? "Messaging unavailable: executor version "
            + `${routing.minimum_version} or newer is required.`
          : "Messaging unavailable: the executor version is not reported "
            + "or supported.",
      };
    }
    return {
      available: false,
      reason:
        "Messaging unavailable: this executor surface has no supported "
        + "delivery hook.",
    };
  }
  if (String(row.liveness || "") !== "active" && routing.wake_available !== true) {
    if (routing.relay_connected === false) {
      return {
        available: false,
        reason:
          "Messaging unavailable: no relay is connected on this session's "
          + "machine.",
      };
    }
    return {
      available: false,
      reason: String(row.liveness || "") === "ended"
        ? "Messaging unavailable: this session has ended and cannot be "
          + "restarted from here."
        : "Messaging unavailable: this idle session has no wake route.",
    };
  }
  return { available: true, reason: "" };
}

export function appendSessionMessaging(documentNode, body, row, onMessage) {
  appendRelay(documentNode, body, row);
  const availability = messagingAvailability(row);
  if (!availability.available) {
    body.appendChild(el(
      documentNode,
      "p",
      "fact-line session-messaging-blocked",
      availability.reason,
    ));
    return;
  }
  const actions = el(documentNode, "div", "session-control-actions");
  const message = el(documentNode, "button", "item-button", "Message");
  message.type = "button";
  message.title = `Message only session ${row.session_id}`;
  message.addEventListener("click", () => onMessage(String(row.session_id)));
  actions.appendChild(message);
  body.appendChild(actions);
}
