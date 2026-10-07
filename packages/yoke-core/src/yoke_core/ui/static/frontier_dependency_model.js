// The Frontier's dependency model: what waits on what, as a general directed
// graph. Nodes are Frontier items, plus a ghost for any blocker the page does
// not otherwise show; edges are the unsatisfied dependency edges frontier.list
// serves, each with a gate (what it holds back on the dependent: start, merge
// or close) and a satisfaction condition (what clears it). An item may wait
// on several blockers, and the engine reports cycles rather than refusing
// them, so a deadlock is a state this model names rather than one it assumes
// away. Nothing here touches the DOM: the graph renderer and the tests read
// the same model.

export const FRONTIER_GATE = { activation: "start", integration: "merge", closure: "close" };
export const FRONTIER_FANOUT_LIMIT = 6;

// What clears an edge, as the blocker's next milestone.
export function frontierCondition(sat) {
  if (sat === "fact:merged") return "merges";
  if (sat === "status:done") return "is done";
  if (sat.startsWith("status:")) return `reaches ${sat.slice(7)}`;
  if (sat.startsWith("fact:deployed:")) return `is live on ${sat.slice(14)}`;
  return sat;
}

// The same milestone as a bare verb, for "will never …".
export function frontierConditionVerb(sat) {
  if (sat === "fact:merged") return "merge";
  if (sat === "status:done") return "be done";
  if (sat.startsWith("status:")) return `reach ${sat.slice(7)}`;
  if (sat.startsWith("fact:deployed:")) return `be live on ${sat.slice(14)}`;
  return sat;
}

// What the edge holds back, from the dependent's side.
export function frontierGatePhrase(edge) {
  const c = `${edge.from} ${frontierCondition(edge.sat)}`;
  return {
    activation: `Starts after ${c}`,
    integration: `Can build now · lands after ${c}`,
    closure: `Can't close until ${c}`,
  }[edge.gate];
}

// Why an edge can never clear on its own, or null. A terminal blocker never
// changes again; an environment no delivery flow of the blocker reaches can
// never make it live there.
export function frontierNever(edge, blocker) {
  if (blocker.terminal) {
    return `${blocker.ref} was ${blocker.stage} — it will never ${frontierConditionVerb(edge.sat)}`;
  }
  if (edge.env && edge.env.in_delivery_flow === false) {
    return `${edge.env.name} is not in ${blocker.ref}'s delivery flow, so it can never be live there`;
  }
  return null;
}

const ENVIRONMENT_STATE = { live: "✓", deploying: "deploying", "not deployed": "not yet" };

// Where a blocker stands in the environment one edge waits on, when the page
// has no delivery reading of its own for that blocker.
export function frontierEdgeDeploy(edge) {
  if (!edge.env) return "";
  return `${edge.env.name} ${ENVIRONMENT_STATE[edge.env.delivery_state] || edge.env.delivery_state}`;
}

function ghost(ref, facts = {}) {
  return {
    ref,
    band: "off",
    stage: facts.stage || "not on this Frontier",
    title: facts.title || "",
    terminal: Boolean(facts.terminal),
    href: facts.href || "",
    projectId: facts.projectId,
  };
}

// Index nodes and edges: blockers and dependents, cycles, each node's own
// reason it cannot move, what is stuck downstream of it, depth, how much it
// unblocks, and the longest chain that can still move.
export function frontierIndex(nodes, edges) {
  for (const n of nodes.values()) { n.blockers = []; n.dependents = []; }
  for (const e of edges) {
    if (!nodes.has(e.from)) nodes.set(e.from, { ...ghost(e.from, e.blockerFacts), blockers: [], dependents: [] });
    if (!nodes.has(e.to)) nodes.set(e.to, { ...ghost(e.to), blockers: [], dependents: [] });
    nodes.get(e.to).blockers.push(e);
    nodes.get(e.from).dependents.push(e);
  }
  // Cycles first: a strongly connected group of two or more never starts.
  const index = new Map(), low = new Map(), stack = [], on = new Set(), cycles = [];
  let i = 0;
  const visit = (v) => {
    index.set(v, i); low.set(v, i++); stack.push(v); on.add(v);
    for (const e of nodes.get(v).dependents) {
      const w = e.to;
      if (!index.has(w)) { visit(w); low.set(v, Math.min(low.get(v), low.get(w))); }
      else if (on.has(w)) low.set(v, Math.min(low.get(v), index.get(w)));
    }
    if (low.get(v) === index.get(v)) {
      const g = [];
      let w;
      do { w = stack.pop(); on.delete(w); g.push(w); } while (w !== v);
      if (g.length > 1) cycles.push(g);
    }
  };
  for (const r of nodes.keys()) if (!index.has(r)) visit(r);
  const inCycle = new Map();
  cycles.forEach((g, k) => g.forEach((r) => inCycle.set(r, k)));

  // A node's own reason it cannot move, then the first stuck blocker upstream.
  for (const n of nodes.values()) {
    n.cycle = inCycle.has(n.ref) ? cycles[inCycle.get(n.ref)] : null;
    n.never = n.blockers.map((e) => frontierNever(e, nodes.get(e.from))).find(Boolean) || null;
    n.stall = n.cycle
      ? `Deadlock — ${n.cycle.join(" ⇄ ")} wait on each other`
      : n.never || (n.dependents.length && n.held ? `${n.held}` : null);
  }
  const stuckMemo = new Map();
  const stuck = (r) => {
    if (stuckMemo.has(r)) return stuckMemo.get(r);
    stuckMemo.set(r, null);
    const n = nodes.get(r);
    let why = n.stall;
    for (const e of n.blockers) {
      if (why) break;
      if (stuck(e.from)) why = `Stuck upstream: ${e.from}`;
    }
    stuckMemo.set(r, why);
    return why;
  };
  // Depth is the longest acyclic path from a node with no blockers.
  const depthMemo = new Map();
  const depth = (r) => {
    if (depthMemo.has(r)) return depthMemo.get(r);
    depthMemo.set(r, 0);
    const n = nodes.get(r);
    const d = n.cycle ? 0 : Math.max(0, ...n.blockers
      .filter((e) => !nodes.get(e.from).cycle || !n.cycle)
      .map((e) => depth(e.from) + 1));
    depthMemo.set(r, d);
    return d;
  };
  const down = (r) => {
    const seen = new Set();
    const walk = (x) => nodes.get(x).dependents.forEach((e) => {
      if (!seen.has(e.to)) { seen.add(e.to); walk(e.to); }
    });
    walk(r);
    seen.delete(r);
    return seen;
  };
  for (const n of nodes.values()) { n.stuck = stuck(n.ref); n.depth = depth(n.ref); n.unblocks = down(n.ref).size; }
  const linked = [...nodes.values()].filter((n) => n.blockers.length || n.dependents.length);
  // The longest chain that can still move: a stuck chain is raised as stuck, not as critical.
  const deepest = linked.filter((n) => !n.cycle && !n.stuck).sort((a, b) => b.depth - a.depth)[0];
  const critical = new Set();
  for (let n = deepest; n;) {
    critical.add(n.ref);
    n = n.blockers.map((e) => nodes.get(e.from)).filter((b) => !b.cycle).sort((a, b) => b.depth - a.depth)[0];
  }
  return {
    nodes,
    edges,
    cycles,
    linked,
    critical: critical.size > 2 ? critical : new Set(),
    roots: linked.filter((n) => !n.blockers.length && !n.cycle)
      .sort((a, b) => b.unblocks - a.unblocks || a.ref.localeCompare(b.ref)),
    lineage: (ref) => {
      const s = new Set([ref]);
      const up = (x) => nodes.get(x).blockers.forEach((e) => { if (!s.has(e.from)) { s.add(e.from); up(e.from); } });
      const dn = (x) => nodes.get(x).dependents.forEach((e) => { if (!s.has(e.to)) { s.add(e.to); dn(e.to); } });
      up(ref);
      dn(ref);
      return s;
    },
  };
}

// The project filter keeps every item `selected` accepts and every item tied
// to one through any dependency chain, whatever project it is in. Only work
// with no link to a selected item drops out.
export function frontierFilter(model, selected) {
  if (!selected) return model;
  const keep = new Set();
  const queue = [...model.nodes.values()].filter(selected).map((n) => n.ref);
  while (queue.length) {
    const r = queue.pop();
    if (keep.has(r)) continue;
    keep.add(r);
    const n = model.nodes.get(r);
    n.blockers.forEach((e) => queue.push(e.from));
    n.dependents.forEach((e) => queue.push(e.to));
  }
  const nodes = new Map([...model.nodes].filter(([r]) => keep.has(r)));
  return frontierIndex(nodes, model.edges.filter((e) => keep.has(e.from) && keep.has(e.to)));
}

// One line under a tile's title: what holds it, or how it is shipping.
export function frontierTileMeta(node) {
  if (node.stuck) return node.stuck;
  const open = node.blockers;
  if (open.length === 1) return frontierGatePhrase(open[0]);
  if (open.length > 1) return `Waits on ${open.length} items`;
  if (node.band === "off") return node.stage;
  return node.deploy || "";
}

// Columns: "holding work up", then one per step behind. Column 0 puts
// deadlocked items last, stalled roots first, then by unblocks and ref; later
// columns follow the mean position of their blockers (barycentre).
export function frontierGraphColumns(model) {
  const cols = [];
  for (const n of model.linked) (cols[n.cycle ? 0 : n.depth] ??= []).push(n);
  const pos = new Map();
  cols.forEach((col, c) => {
    const score = (n) => {
      const ps = n.blockers.map((e) => pos.get(e.from)).filter((p) => p !== undefined);
      return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : -1;
    };
    col.sort(c === 0
      ? (a, b) => (!!a.cycle - !!b.cycle) || (!!b.stall - !!a.stall) || b.unblocks - a.unblocks || a.ref.localeCompare(b.ref)
      : (a, b) => score(a) - score(b) || b.unblocks - a.unblocks || a.ref.localeCompare(b.ref));
    col.forEach((n, i) => pos.set(n.ref, i / Math.max(1, col.length)));
  });
  return cols;
}

export function frontierColumnHeading(c) {
  return c === 0 ? "Holding work up" : `${c} step${c === 1 ? "" : "s"} behind`;
}

// One column's tiles in order. More than the fan-out limit of leaves that
// wait only on the same single blocker fold after the limit's last visible
// place into one stack entry, which carries the folded refs and gate phrase.
export function frontierColumnPlan(col) {
  const out = [], stacked = new Set();
  const leafOf = (m) => (m.blockers.length === 1 && !m.dependents.length ? m.blockers[0].from : null);
  for (const n of col) {
    const only = leafOf(n);
    const siblings = only ? col.filter((m) => leafOf(m) === only) : [];
    if (siblings.length > FRONTIER_FANOUT_LIMIT && siblings.indexOf(n) >= FRONTIER_FANOUT_LIMIT - 1) {
      if (!stacked.has(only)) {
        const rest = siblings.slice(FRONTIER_FANOUT_LIMIT - 1);
        stacked.add(only);
        out.push({ kind: "stack", refs: rest.map((m) => m.ref), phrase: frontierGatePhrase(rest[0].blockers[0]) });
      }
      continue;
    }
    out.push({ kind: "tile", ref: n.ref });
  }
  return out;
}

// The phone outline: each chain as a tree from its root, each item once,
// roots first and then any deadlocked group.
export function frontierOutline(model) {
  const placed = new Set();
  const branch = (ref) => {
    placed.add(ref);
    const kids = model.nodes.get(ref).dependents.map((e) => e.to).filter((r) => !placed.has(r));
    const children = [];
    for (const k of kids) if (!placed.has(k)) children.push(branch(k));
    return { ref, children };
  };
  const trees = [];
  for (const r of [...model.roots.map((n) => n.ref), ...model.cycles.flat()]) {
    if (!placed.has(r)) trees.push(branch(r));
  }
  return trees;
}

// Waiting items held for a reason of their own with nothing waiting on them
// are On hold; every other waiting item is drawn in the graph.
export function frontierWaitingSplit(model) {
  const waiting = [...model.nodes.values()].filter((n) => n.band === "waiting");
  const held = waiting.filter((n) => !n.blockers.length && !n.dependents.length);
  return { held, graphCount: waiting.length - held.length };
}
