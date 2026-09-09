// Stable workbench destinations, their groups, and their project-scope
// contracts.
//
// Three groups, and the second and third exist to say something honest about
// the first. FOCUS is what an operator opens. SETTINGS is configuration that
// persists. DIAGNOSTICS is everything else — and it is a drawer on purpose,
// not a filing failure: those destinations are unproven, several of them
// window onto things an agent authors in the CLI rather than anything a person
// builds here, and one flat list of twenty claimed they were all equally worth
// going to. A destination leaves the drawer when it earns a reason to be
// looked at.
//
// Settings sits above Diagnostics because it is the group you open on purpose;
// the drawer is where you end up, not where you head.

export const SCOPE_MULTI = "multi", SCOPE_SINGLE = "single";
export const SCOPE_NONE = "none";

export const GROUP_FOCUS = "focus";
export const GROUP_SETTINGS = "settings";
export const GROUP_DIAGNOSTICS = "diagnostics";

// Render order, and the label each group carries in the sidebar. Focus is
// unlabelled: it is the top of the list and needs no heading to say so.
export const NAV_GROUPS = [
  { id: GROUP_FOCUS, label: "" },
  { id: GROUP_SETTINGS, label: "Settings" },
  { id: GROUP_DIAGNOSTICS, label: "Diagnostics" },
];

export const NAV = [
  {
    id: "overview", icon: "⊞", label: "Overview", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  {
    id: "sessions", icon: "◈", label: "Sessions", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  {
    id: "inbox", icon: "✉", label: "Inbox", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },

  // A workflow definition is configuration: it is authored once and every item
  // then follows the version pinned to it. What you govern with is not what
  // you watch.
  {
    id: "organization", icon: "⛭", label: "Universe", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "workflows", icon: "⚗", label: "Workflows", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "projects", icon: "▤", label: "Projects", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "github", icon: "⎇", label: "GitHub", scope: SCOPE_MULTI,
    group: GROUP_SETTINGS,
  },
  {
    id: "actors", icon: "⚇", label: "Actors", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  // Registration and proved identity per registered machine. Which machines
  // exist is configuration you maintain, so it sits with the rest of it;
  // capacity and health are a different question and stay on Sessions, where
  // they are read before staffing rather than after.
  {
    id: "machines", icon: "▣", label: "Machines", scope: SCOPE_MULTI,
    group: GROUP_SETTINGS,
  },
  {
    id: "members", icon: "⚉", label: "Members", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    hostFed: true,
  },
  {
    id: "billing", icon: "▧", label: "Billing", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    hostFed: true,
  },

  // Ordered by subject, in the order the subjects follow each other: what the
  // work is, how it ships, how it is proved, what the project is made of, and
  // the record of what happened. Alphabetical would have been an order too,
  // and a worse one — it puts Architecture beside Capabilities because both
  // start with a letter.
  {
    id: "strategy", icon: "❖", label: "Strategy", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "items", icon: "≣", label: "Items", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "deployments", icon: "⬈", label: "Deployments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "environments", icon: "◇", label: "Environments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "flows", icon: "⇉", label: "Flows", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "databases", icon: "▤", label: "Databases", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-methods", icon: "◉", label: "QA methods", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-plans", icon: "◎", label: "QA plans", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-activity", icon: "◍", label: "QA activity", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "capabilities", icon: "⚿", label: "Capabilities", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    pageAction: { label: "Add capability", view: "projects" },
  },
  {
    id: "packs", icon: "◫", label: "Packs", scope: SCOPE_NONE,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "architecture", icon: "▦", label: "Architecture", scope: SCOPE_SINGLE,
    group: GROUP_DIAGNOSTICS,
  },
  // Fleet-wide traffic, which is not the Inbox: the Inbox is yours.
  {
    id: "messages", icon: "✦", label: "Messages", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "launches", icon: "⇱", label: "Launches", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "events", icon: "≋", label: "Events", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "doctor", icon: "♥", label: "Doctor", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "ouroboros", icon: "∞", label: "Ouroboros", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
];
