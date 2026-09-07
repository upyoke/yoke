// One remembered selection per actor and universe; focus never replaces it.
export function knownProjectId(projects, candidate) {
  return projects.some((row) => String(row.id) === String(candidate))
    ? String(candidate) : null;
}

export function projectSelection(projects, candidate) {
  if (candidate === "all") return "all";
  const ids = new Set(Array.isArray(candidate)
    ? candidate.map(String) : String(candidate || "").split(",").map((id) => id.trim()));
  const known = projects.map((row) => String(row.id)).filter((id) => ids.has(id));
  return known.length ? known : "all";
}

export function selectionParam(selection) {
  return Array.isArray(selection) ? selection.join(",") : "all";
}

export function createProjectSelection(windowNode, identity) {
  let storage = null, key = null;
  const state = { selection: "all", focus: null, notice: "" };
  const report = () => {
    state.notice = "Project selection cannot be saved. Allow browser storage to remember it after reload.";
  };
  if (identity) {
    if (!String(identity.universeId || "").trim() ||
        !String(identity.actorId ?? "").trim()) {
      throw new TypeError("project_selection_identity_invalid: supply universeId and actorId, or omit selectionIdentity for an unidentified viewer");
    }
    key = `yoke.project-selection:${JSON.stringify([
      String(identity.universeId), String(identity.actorId),
    ])}`;
    try {
      storage = windowNode.localStorage;
      if (!storage) report();
      const saved = JSON.parse(storage?.getItem(key) || "null");
      if (saved && (saved.selection === "all" || Array.isArray(saved.selection))) {
        state.selection = saved.selection;
        state.focus = saved.focus;
      }
    } catch { report(); }
  }
  state.save = () => {
    if (!storage) return;
    try {
      storage.setItem(key, JSON.stringify({ selection: state.selection, focus: state.focus }));
    } catch { report(); }
  };
  return state;
}

export function resolveProjectSelection(state, projects, explicitSelection) {
  state.selection = projectSelection(
    projects, explicitSelection ?? state.selection,
  );
  state.focus = knownProjectId(projects, state.focus);
  state.save();
  return state.selection;
}
