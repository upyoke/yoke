// Host-neutral plumbing for the optional mount seam: root validation, slot
// and section materialization, and unmount bookkeeping. This stays separate
// from the workbench views so the one-argument local mount remains small. Host
// capability actions are not chrome — the Organization view renders them
// (universe_views_organization.js).

const MOUNT_ROOT_CLASS = "universe-app-root";
const HTML_NAMESPACE = "http://www.w3.org/1999/xhtml";
const SLOT_NAMES = [
  "topbarStart",
  "topbarEnd",
  "navigationStart",
  "navigationEnd",
  "contentBefore",
  "contentAfter",
];

export function attachMountRootClass(rootNode) {
  const alreadyPresent = rootNode.classList.contains(MOUNT_ROOT_CLASS);
  rootNode.classList.add(MOUNT_ROOT_CLASS);
  return () => {
    if (!alreadyPresent) rootNode.classList.remove(MOUNT_ROOT_CLASS);
  };
}

export function validateMountRoot(rootNode) {
  if (!rootNode || rootNode.namespaceURI !== HTML_NAMESPACE ||
      typeof rootNode.replaceChildren !== "function") {
    throw new TypeError("mountUniverseApp requires an HTML element root");
  }
}

export function createUnmountHandle(contractVersion, cleanup) {
  let pendingCleanup = cleanup;
  return {
    contractVersion,
    unmount() {
      if (pendingCleanup === null) return;
      const release = pendingCleanup;
      pendingCleanup = null;
      release();
    },
  };
}

// One validation for every host-supplied content node, slot or section: an
// Element (or a factory yielding one), never the mount root or its ancestor,
// and never the same node twice — the shared `seen` set makes a node placed
// as both a slot and a section one collision, not two placements.
function materializeContent(candidate, rootNode, seen, kind) {
  const content = typeof candidate === "function" ? candidate() : candidate;
  if (content === undefined || content === null) return null;
  if (content.nodeType !== 1) {
    throw new TypeError(`universe app ${kind} content must be an Element`);
  }
  if (content === rootNode || content.contains(rootNode)) {
    throw new TypeError(
      `${kind} content cannot be the mount root or its ancestor`,
    );
  }
  if (seen.has(content)) {
    throw new TypeError(
      "one Element cannot occupy two universe app slots or sections",
    );
  }
  seen.add(content);
  return content;
}

export function materializeSlots(slots, rootNode, seen = new Set()) {
  const resolved = {};
  for (const name of SLOT_NAMES) {
    const content = materializeContent(slots[name], rootNode, seen, "slot");
    if (content !== null) resolved[name] = content;
  }
  return resolved;
}

const SECTION_PLACEMENTS = ["inView", "beforeScope"];

// A section entry is a bare node/factory (the `inView` shorthand) or a spec
// naming its content and placement. Content is told apart first, by being a
// node or a factory — a spec is only ever a plain options object. Asking
// instead whether the entry carries a `content` key would misread a
// <template>, which owns a `content` property of its own.
function sectionSpec(entry) {
  const isContent = entry === undefined || entry === null ||
    typeof entry === "function" || typeof entry.nodeType === "number";
  if (isContent) return { content: entry };
  const placement = entry.placement ?? "inView";
  if (!SECTION_PLACEMENTS.includes(placement)) {
    throw new TypeError(
      `universe app section placement must be one of ${
        SECTION_PLACEMENTS.join(", ")}`,
    );
  }
  return { content: entry.content, placement };
}

// Per-view host content. Keys are view ids — an open record rather than a
// closed roster, because the views a host may feed belong to the navigation
// module, not to this plumbing. Each resolved entry keeps its placement
// beside its node, so the renderer never re-reads the host's option bag.
export function materializeSections(sections, rootNode, seen = new Set()) {
  const resolved = {};
  for (const name of Object.keys(sections)) {
    const spec = sectionSpec(sections[name]);
    const content = materializeContent(
      spec.content, rootNode, seen, "section",
    );
    if (content !== null) {
      resolved[name] = { content, placement: spec.placement ?? "inView" };
    }
  }
  return resolved;
}

export function appendSlot(container, slot, mountedSlotNodes) {
  if (slot === undefined || slot === null) return;
  container.appendChild(slot);
  mountedSlotNodes.push(slot);
}

function isInsideRoot(rootNode, candidate) {
  for (let node = candidate; node; node = node.parentNode) {
    if (node === rootNode) return true;
  }
  return false;
}

export function detachMountedSlots(rootNode, mountedSlotNodes) {
  for (const slotNode of mountedSlotNodes) {
    if (isInsideRoot(rootNode, slotNode) && slotNode.parentNode) {
      slotNode.parentNode.removeChild(slotNode);
    }
  }
}
