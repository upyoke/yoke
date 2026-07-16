// Host-neutral plumbing for the optional mount seam: root validation, slot
// materialization, and unmount bookkeeping. This stays separate from the
// workbench views so the one-argument local mount remains small. Host
// capability actions are not chrome — the Universe settings view renders
// them (universe_views_settings.js).

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

export function materializeSlots(slots, rootNode) {
  const resolved = {};
  const seen = new Set();
  for (const name of SLOT_NAMES) {
    const slot = slots[name];
    const content = typeof slot === "function" ? slot() : slot;
    if (content === undefined || content === null) continue;
    if (content.nodeType !== 1) {
      throw new TypeError("universe app slot content must be an Element");
    }
    if (content === rootNode || content.contains(rootNode)) {
      throw new TypeError("slot content cannot be the mount root or its ancestor");
    }
    if (seen.has(content)) {
      throw new TypeError("one Element cannot occupy two universe app slots");
    }
    seen.add(content);
    resolved[name] = content;
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
