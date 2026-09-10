// One remembered selection per actor, kept independently for each
// workbench screen: changing Sessions' selection never touches Inbox's or
// Overview's. The server (`actor_ui_preferences`, via
// `ui_preferences.screen_selection.*`) is the store of record, so a
// screen's choice survives reload, a new tab, or a different browser for
// the same actor — `saveView` (bound by the caller to the live
// function-call client) is the only way values leave this module.
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

export function createProjectSelection(saveView, onNotice) {
  const views = new Map();
  // `ready` gates every write: until the initial server read has genuinely
  // succeeded (seeding what the actor actually has on record, even an
  // empty map), this module knows nothing about the true stored state, so
  // a normalization default must never be persisted over it. An
  // unsuccessful initial read leaves `ready` false for the life of this
  // mount — every subsequent selection still renders correctly from
  // in-memory defaults, it just is not written through.
  const state = { notice: "", ready: false };
  // A save can settle long after the render that started it, with nothing
  // else about to re-render — `onNotice` (the caller's re-render hook) is
  // what makes its notice visible without another navigation.
  state.setNotice = (text) => {
    state.notice = text;
    onNotice?.();
  };
  // The initial load's own failure, in contrast, always settles BEFORE the
  // mount bootstrap's own first render — that render already reads
  // `notice` fresh, so setting it here needs no `onNotice` trigger, and
  // firing one anyway would force a second, premature render/refetch race
  // with the bootstrap's real one.
  state.seedNotice = (text) => { state.notice = text; };
  const entryFor = (viewId) => {
    let entry = views.get(viewId);
    if (!entry) { entry = { selection: "all", focus: null }; views.set(viewId, entry); }
    return entry;
  };
  state.selectionFor = (viewId) => entryFor(viewId).selection;
  state.focusFor = (viewId) => entryFor(viewId).focus;
  state.setSelectionFor = (viewId, selection) => { entryFor(viewId).selection = selection; };
  state.setFocusFor = (viewId, focus) => { entryFor(viewId).focus = focus; };
  // Seeds a view's remembered value with no save round trip: the mount
  // bootstrap uses this to install what the server already has on record.
  state.seed = (viewId, selection, focus = null) => {
    views.set(viewId, { selection, focus });
  };
  // Marks the initial server read as genuinely settled — called only after
  // that read succeeds, whether or not it had anything to seed.
  state.markReady = () => { state.ready = true; };
  state.saveFor = (viewId) => {
    if (!saveView || !state.ready) return;
    const entry = entryFor(viewId);
    Promise.resolve()
      .then(() => saveView(viewId, entry.selection, entry.focus))
      .catch(() => {
        state.setNotice("Project selection could not be saved. It may not " +
          "carry over to another tab, session, or reload.");
      });
  };
  return state;
}

// Normalizes a view's selection/focus against the live project roster,
// persists only when normalization actually changed something, and
// returns the resolved selection.
export function resolveProjectSelection(state, viewId, projects, explicitSelection) {
  const priorSelection = state.selectionFor(viewId);
  const priorFocus = state.focusFor(viewId);
  const selection = projectSelection(projects, explicitSelection ?? priorSelection);
  const focus = knownProjectId(projects, priorFocus);
  state.setSelectionFor(viewId, selection);
  state.setFocusFor(viewId, focus);
  if (selectionParam(selection) !== selectionParam(priorSelection) || focus !== priorFocus) {
    state.saveFor(viewId);
  }
  return selection;
}
