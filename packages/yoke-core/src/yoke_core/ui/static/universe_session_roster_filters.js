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

function unavailableReason(routing) {
  if (routing.reason === "session_terminated") {
    return "Messaging unavailable: this session is permanently terminated.";
  }
  if (routing.reason === "version_below_floor_or_unknown") {
    return routing.minimum_version
      ? `Messaging unavailable: executor version ${routing.minimum_version} or newer is required.`
      : "Messaging unavailable: the executor version is not supported.";
  }
  if (routing.reason === "unknown_surface") {
    return "Messaging unavailable: this executor surface is not supported.";
  }
  return "Messaging unavailable: this surface has no supported delivery hook.";
}

export function sessionMessageabilityText(row) {
  const routing = row.messageability || {};
  if (routing.messageable !== true) return unavailableReason(routing);
  if (routing.wake_available === true) {
    return row.liveness === "ended"
      ? "Messageable: durable delivery and automatic restart are available."
      : "Messageable: durable delivery and automatic wake are available.";
  }
  return row.liveness === "ended"
    ? "Messageable: a message can queue, but automatic restart is unavailable."
    : "Messageable through a supported hook; automatic wake is unavailable.";
}

function machineFactLabel(row) {
  return row.machine_name || row.machine_id || "not reported";
}

export function appendSessionMessaging(documentNode, body, row, onMessage) {
  const relay = row.relay ? ` · relay ${row.relay}` : "";
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-executor-version",
    `Executor version: ${row.executor_version || "not reported"}`,
  ));
  const machine = el(
    documentNode,
    "p",
    "fact-line session-machine-fact",
    `Machine: ${machineFactLabel(row)}${relay}`,
  );
  if (row.machine_id) machine.title = String(row.machine_id);
  body.appendChild(machine);
  const description = sessionMessageabilityText(row);
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-messageability",
    description,
  ));
  const actions = el(documentNode, "div", "session-control-actions");
  const message = el(documentNode, "button", "item-button", "Message");
  message.type = "button";
  message.disabled = row.messageability?.messageable !== true;
  message.title = message.disabled
    ? description
    : `Message only session ${row.session_id}`;
  message.addEventListener("click", () => {
    if (!message.disabled) onMessage(String(row.session_id));
  });
  actions.appendChild(message);
  body.appendChild(actions);
}
