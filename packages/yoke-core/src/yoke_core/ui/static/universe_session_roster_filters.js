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

export function sessionRosterFilters(documentNode, onChange) {
  const host = el(documentNode, "div", "session-roster-filters");
  const controls = {};
  for (const [name, label] of [
    ["search", "Search"], ["executor", "Executor"], ["surface", "Surface"],
    ["role", "Role"], ["lane", "Execution lane"],
    ["worktree", "Worktree"], ["machine", "Machine"],
  ]) {
    const field = input(documentNode, label);
    controls[name] = field.control;
    host.appendChild(field.wrapper);
  }
  const liveness = input(documentNode, "Liveness", "select");
  for (const value of ["", "active", "stale"]) {
    liveness.control.appendChild(option(
      documentNode, value, value || "Any liveness",
    ));
  }
  controls.liveness = liveness.control;
  host.appendChild(liveness.wrapper);
  const route = input(documentNode, "Route", "select");
  for (const [value, label] of [
    ["", "Any route"], ["message", "Messageable"], ["wake", "Wakeable"],
  ]) route.control.appendChild(option(documentNode, value, label));
  controls.route = route.control;
  host.appendChild(route.wrapper);
  for (const control of Object.values(controls)) {
    control.addEventListener("input", onChange);
    control.addEventListener("change", onChange);
  }
  return {
    host,
    apply(rows) {
      const query = String(controls.search.value || "").toLowerCase();
      return rows.filter((row) => {
        const searchable = [
          row.session_id, row.project, row.focus, row.actor_label,
          row.current_item_title, row.model,
        ].join(" ").toLowerCase();
        const routing = row.messageability || {};
        return (!query || searchable.includes(query))
          && includes(row.executor, String(controls.executor.value || "").toLowerCase())
          && includes(row.executor_surface, String(controls.surface.value || "").toLowerCase())
          && includes(row.role || row.work_role, String(controls.role.value || "").toLowerCase())
          && includes(row.execution_lane, String(controls.lane.value || "").toLowerCase())
          && includes(row.worktree, String(controls.worktree.value || "").toLowerCase())
          && includes(row.machine_id, String(controls.machine.value || "").toLowerCase())
          && (!controls.liveness.value || row.liveness === controls.liveness.value)
          && (controls.route.value !== "message" || routing.messageable === true)
          && (controls.route.value !== "wake" || routing.wake_available === true);
      });
    },
  };
}
