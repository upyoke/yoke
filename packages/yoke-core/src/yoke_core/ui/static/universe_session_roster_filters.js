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
const ACTIVE_LIVENESS = new Set([DEFAULT_STATE, "stale"]);

function selectedValues(rows, valueFor) {
  return [...new Set(rows.map(valueFor).filter(Boolean))].sort(
    (left, right) => left.localeCompare(right),
  );
}

function setOptions(documentNode, control, defaultLabel, values) {
  const selected = String(control.value || "");
  control.replaceChildren(option(documentNode, "", defaultLabel));
  for (const value of values) {
    control.appendChild(option(documentNode, value, value));
  }
  control.value = values.includes(selected) ? selected : "";
}

function matchesState(liveness, selected) {
  const value = String(liveness || "").toLowerCase();
  if (!selected) return true;
  if (selected === DEFAULT_STATE) return ACTIVE_LIVENESS.has(value);
  return selected === "ended" && value === "ended";
}

export function sessionRosterFilters(documentNode, onChange) {
  const host = el(documentNode, "div", "session-roster-filters");
  host.setAttribute("role", "search");
  host.setAttribute("aria-label", "Filter sessions");
  const controls = {};
  const search = input(documentNode, null, "search");
  search.wrapper.classList.add("session-filter-search");
  search.control.placeholder = "Search sessions, items, models, operators";
  search.control.setAttribute("aria-label", "Search");
  search.wrapper.replaceChildren(
    el(documentNode, "span", "session-filter-search-icon", "⌕"),
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
  for (const [name, label] of [["harness", "Harness"], ["machine", "Machine"]]) {
    const field = input(documentNode, label, "select");
    field.control.appendChild(option(documentNode, "", `Any ${name}`));
    controls[name] = field.control;
    host.appendChild(field.wrapper);
  }
  const clear = el(documentNode, "button", "session-filter-clear", "Clear");
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
  const actions = el(documentNode, "span", "session-filter-actions");
  host.appendChild(actions);
  return {
    actions,
    host,
    setRows(rows) {
      setOptions(documentNode, controls.harness, "Any harness", selectedValues(
        rows,
        (row) => String(
          row.presentation_surface || row.executor_surface || row.executor || "",
        ),
      ));
      setOptions(documentNode, controls.machine, "Any machine", selectedValues(
        rows,
        (row) => String(row.machine_name || row.machine_id || ""),
      ));
      clear.disabled = !hasChanges();
    },
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
          row.current_item_title, row.model, row.requested_model,
        ].join(" ").toLowerCase();
        return (!query || searchable.includes(query))
          && (!harness || includes(row.executor, harness)
            || includes(row.executor_surface, harness)
            || includes(row.presentation_surface, harness))
          && (
            includes(row.machine_id, String(controls.machine.value || "").toLowerCase())
            || includes(row.machine_name, String(controls.machine.value || "").toLowerCase())
          )
          && matchesState(row.liveness, controls.state.value);
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
export function appendSessionRelay(documentNode, body, row) {
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
//
// A desktop surface has no such route by design: Yoke never resumes the
// window a person is reading. A message to a quiet one still arrives — on
// that operator's next turn — so delivery stays available and the wait is
// reported as a `note` rather than a blocker. The card already shows that
// wait in its parked badge and footer, so the note rides the Message
// button's tooltip instead of taking a line of its own.
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
    if (String(row.liveness || "") !== "ended"
      && routing.wake_authority === "operator") {
      return {
        available: true,
        reason: "",
        note: "Waiting for the operator to wake it: a message is delivered "
          + "when they next type anything in this chat.",
      };
    }
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

export function sessionMessageButton(documentNode, row, onMessage) {
  const availability = messagingAvailability(row);
  if (!availability.available) return null;
  const message = el(
    documentNode,
    "button",
    "item-button session-message-button",
    "Message",
  );
  message.type = "button";
  message.title = availability.note
    || `Message only session ${row.session_id}`;
  message.addEventListener("click", () => onMessage(String(row.session_id)));
  return message;
}

// Only a genuine blocker earns a line. When messaging is unavailable the
// Message button is gone, so this paragraph is the sole feedback for why.
export function appendSessionMessagingBlocker(documentNode, body, row) {
  const availability = messagingAvailability(row);
  if (availability.available) return;
  body.appendChild(el(
    documentNode,
    "p",
    "fact-line session-messaging-blocked",
    availability.reason,
  ));
}
