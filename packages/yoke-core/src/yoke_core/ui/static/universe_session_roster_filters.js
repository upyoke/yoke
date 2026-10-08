import { magnifier } from "./universe_search_overlay.js";
import { sessionIsLive } from "./universe_session_diagnostics.js";
import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

function input(documentNode, label, kind = "text") {
  const wrapper = el(documentNode, "label", "session-roster-filter");
  if (label) wrapper.appendChild(el(
    documentNode, "span", "session-filter-label", label,
  ));
  const control = el(documentNode, kind === "select" ? "select" : "input");
  control.className = "session-filter-control";
  if (kind !== "select") control.type = kind;
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

function setOptions(documentNode, control, defaultLabel, values) {
  setOptionEntries(documentNode, control, defaultLabel, values.map(
    (value) => ({ value, label: value }),
  ));
}

function setOptionEntries(documentNode, control, defaultLabel, entries) {
  const selected = String(control.value || "");
  control.replaceChildren(option(documentNode, "", defaultLabel));
  for (const entry of entries) {
    control.appendChild(option(documentNode, String(entry.value), entry.label));
  }
  control.value = entries.some((entry) => String(entry.value) === selected)
    ? selected : "";
}

function matchesState(liveness, selected) {
  const value = String(liveness || "").toLowerCase();
  if (!selected) return true;
  if (selected === DEFAULT_STATE) return sessionIsLive({ liveness: value });
  return selected === "ended" && value === "ended";
}

export function sessionRosterFilters(documentNode, onChange) {
  const host = el(documentNode, "div", "session-roster-filters sessions-toolbar");
  host.setAttribute("role", "search");
  host.setAttribute("aria-label", "Filter sessions");
  const controls = {};
  const search = input(documentNode, null, "search");
  search.wrapper.classList.add("session-filter-search");
  search.control.placeholder = "Search sessions, items, models, operators";
  search.control.setAttribute("aria-label", "Search");
  search.wrapper.replaceChildren(
    magnifier(documentNode, "session-filter-search-icon"),
    search.control,
  );
  controls.search = search.control;
  host.appendChild(search.wrapper);
  const state = input(documentNode, "State", "select");
  for (const [value, label] of [
    ["active", "Active"], ["ended", "Ended"], ["", "All"],
  ]) {
    state.control.appendChild(option(documentNode, value, label));
  }
  state.control.value = DEFAULT_STATE;
  controls.state = state.control;
  host.appendChild(state.wrapper);
  for (const [name, label] of [
    ["project", "Project"], ["harness", "Harness"], ["machine", "Machine"],
  ]) {
    const field = input(documentNode, label, "select");
    field.control.appendChild(option(documentNode, "", "Any"));
    controls[name] = field.control;
    host.appendChild(field.wrapper);
  }
  const clear = el(documentNode, "button", "session-filter-clear", "Clear");
  clear.type = "button";
  clear.disabled = true;
  const hasChanges = () => String(controls.search.value || "").trim()
    || String(controls.harness.value || "").trim()
    || String(controls.machine.value || "").trim()
    || String(controls.project.value || "").trim()
    || controls.state.value !== DEFAULT_STATE;
  const changed = (key = "unknown") => {
    clear.disabled = !hasChanges();
    onChange(key);
  };
  for (const [key, control] of Object.entries(controls)) {
    control.addEventListener("input", () => changed(key));
    control.addEventListener("change", () => changed(key));
  }
  clear.addEventListener("click", () => {
    controls.search.value = "";
    controls.project.value = "";
    controls.harness.value = "";
    controls.machine.value = "";
    controls.state.value = DEFAULT_STATE;
    changed("clear");
  });
  // Clear leads the roster actions rather than standing alone, so the
  // toolbar lays out as search, actions, and four equal filters.
  const actions = el(documentNode, "span", "session-filter-actions");
  actions.appendChild(clear);
  host.appendChild(actions);
  const applyRows = (rows, includeState) => {
    const query = String(controls.search.value || "").toLowerCase();
    const harness = String(controls.harness.value || "").toLowerCase();
    const project = String(controls.project.value || "").toLowerCase();
    const machine = String(controls.machine.value || "").toLowerCase();
    return rows.filter((row) => {
      const searchable = [
        row.session_id, row.project, row.focus, row.actor_label,
        row.current_item_title, row.model, row.requested_model,
      ].join(" ").toLowerCase();
      return (!query || searchable.includes(query))
        && (!project || String(row.project_id || "").toLowerCase() === project
          || String(row.project || "").toLowerCase() === project)
        && (!harness || includes(row.executor, harness)
          || includes(row.executor_surface, harness)
          || includes(row.presentation_surface, harness))
        && (includes(row.machine_id, machine) || includes(row.machine_name, machine))
        && (!includeState || matchesState(row.liveness, controls.state.value));
    });
  };
  return {
    actions,
    host,
    setFacets(facets = {}) {
      setOptionEntries(documentNode, controls.project, "Any",
        (facets.projects || []).map((entry) => ({
          value: String(entry.id), label: String(entry.slug || entry.id),
        })));
      setOptions(documentNode, controls.harness, "Any", facets.harnesses || []);
      setOptionEntries(documentNode, controls.machine, "Any",
        (facets.machines || []).map((entry) => ({
          value: String(entry.id), label: String(entry.label || entry.id),
        })));
      clear.disabled = !hasChanges();
    },
    state() {
      return String(controls.state.value || "");
    },
    historyCriteria(scopeProjects = []) {
      const selectedProject = String(controls.project.value || "").trim();
      return {
        search: String(controls.search.value || "").trim(),
        projects: selectedProject ? [selectedProject] : scopeProjects,
        harnesses: String(controls.harness.value || "").trim()
          ? [String(controls.harness.value)] : [],
        machines: String(controls.machine.value || "").trim()
          ? [String(controls.machine.value)] : [],
      };
    },
    isRestrictive() {
      return Boolean(
        String(controls.search.value || "").trim()
        || String(controls.project.value || "").trim()
        || String(controls.harness.value || "").trim()
        || String(controls.machine.value || "").trim()
        || controls.state.value,
      );
    },
    summary() {
      const values = [`State: ${controls.state.value || "any"}`];
      for (const [key, label] of [
        ["search", "Search"], ["project", "Project"],
        ["harness", "Harness"], ["machine", "Machine"],
      ]) {
        const value = String(controls[key].value || "").trim();
        if (value) values.push(`${label}: ${value}`);
      }
      return values;
    },
    apply(rows) {
      return applyRows(rows, true);
    },
    applyOpen(rows) {
      return applyRows(rows, false);
    },
  };
}

function machineLabel(row) {
  return row.machine_name || row.machine_id || "machine not reported";
}

export function appendSessionRelay(documentNode, body, row) {
  const ended = String(row.liveness || "") === "ended";
  const line = el(
    documentNode, "div", ended ? "session-relay is-muted" : "session-relay",
  );
  line.appendChild(el(documentNode, "span", "session-relay-label", "Relay:"));
  const connected = row.relay === "connected";
  // An ended session is not waiting on a relay, and a history row reports no
  // relay state at all, so its machine reads idle rather than critical: the
  // alarm belongs to a live session whose messages have nowhere to land.
  const tone = connected ? "good" : (ended ? "idle" : "crit");
  const pill = el(
    documentNode, "span", `pill ${tone} session-relay-pill`,
  );
  pill.appendChild(el(
    documentNode, "span", "session-relay-machine", machineLabel(row),
  ));
  pill.setAttribute("data-state", connected ? "connected" : "unavailable");
  // Deliberately the browser's own title rather than the shared tooltip: the
  // pill's text already IS this label, clipped to 22ch by the sheet, so the
  // reveal repeats visible characters instead of explaining anything.
  pill.title = machineLabel(row);
  line.appendChild(pill);
  // A missing relay is a live session's problem to solve; an ended one has
  // nothing left to reach, so its card names the machine without raising an
  // alarm about a connection nobody is waiting on.
  if (!connected && String(row.liveness || "") !== "ended") {
    line.appendChild(el(
      documentNode,
      "span",
      "session-relay-warning",
      "no relay connected",
    ));
  }
  body.appendChild(line);
}

export function sessionMessageDeliveryNote(row) {
  const routing = row.messageability || {};
  if (String(row.liveness || "") === "active"
      && row.mode !== "parked" && row.turn_posture !== "waiting") return "";
  if (routing.wake_authority === "operator") {
    return "Queued — delivered when you wake this session.";
  }
  if (routing.relay_connected === false) {
    return "Queued — delivered on this session's next hook. Automatic wake "
      + "waits for the relay to reconnect.";
  }
  return "";
}

export function sessionMessageButton(documentNode, row, onMessage) {
  const message = el(
    documentNode,
    "button",
    "item-button session-message-button",
    "Message",
  );
  message.type = "button";
  attachTooltip(
    documentNode,
    message,
    sessionMessageDeliveryNote(row) || `Message only session ${row.session_id}`,
    { pinOnClick: false },
  );
  message.addEventListener("click", () => onMessage(String(row.session_id)));
  return message;
}

export function appendSessionMessageDeliveryNote(documentNode, body, row) {
  const note = sessionMessageDeliveryNote(row);
  if (!note) return;
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-message-delivery-note",
    note,
  ));
}
