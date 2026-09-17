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
// Focus follows the working day rather than the data model: where the
// universe is pointed (Strategy), what is moving (Frontier), what is going
// out (Shipping), what it runs on (Machines), who is running it (Sessions),
// and what is waiting on you (Inbox). Each is one page. The single Overview
// that used to stack Strategy, Frontier and Shipping under collapsible bands
// made the operator scroll past two subjects to reach the third.
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
// Diagnostics is collapsible; `collapsible` is what marks the group whose
// heading toggles its destinations.
export const NAV_GROUPS = [
  { id: GROUP_FOCUS, label: "" },
  { id: GROUP_SETTINGS, label: "Settings" },
  { id: GROUP_DIAGNOSTICS, label: "Diagnostics", collapsible: true },
];

export const NAV = [
  // Where the universe is pointed: its standing documents and its plans,
  // with the write history under them.
  {
    id: "strategy", label: "Strategy", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  // Work moving through its bands — waiting, ready, active, done.
  {
    id: "frontier", label: "Frontier", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  // Deployment runs as they execute, with what each release carries.
  {
    id: "shipping", label: "Shipping", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  // Capacity and health per registered machine, with the registration
  // identity that proves each one. The roster is universe-wide: project
  // chips do not filter it.
  {
    id: "machines", label: "Machines", scope: SCOPE_NONE,
    group: GROUP_FOCUS,
  },
  {
    id: "sessions", label: "Sessions", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  {
    id: "inbox", label: "Inbox", scope: SCOPE_MULTI,
    group: GROUP_FOCUS,
  },
  // The person's own page. Reached from the actor menu, never the sidebar:
  // the sidebar lists the universe's destinations, and a person is not one.
  {
    id: "profile", label: "Profile", scope: SCOPE_NONE,
    group: GROUP_FOCUS, hidden: true,
  },

  // A workflow definition is configuration: it is authored once and every item
  // then follows the version pinned to it. What you govern with is not what
  // you watch.
  {
    id: "organization", label: "Universe", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "workflows", label: "Workflows", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "projects", label: "Projects", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "github", label: "GitHub", scope: SCOPE_MULTI,
    group: GROUP_SETTINGS,
  },
  {
    id: "actors", label: "Actors", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
  },
  {
    id: "members", label: "Members", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    hostFed: true,
  },
  {
    id: "billing", label: "Billing", scope: SCOPE_NONE,
    group: GROUP_SETTINGS,
    hostFed: true,
  },

  // Ordered by subject, in the order the subjects follow each other: what the
  // work is, how it ships, how it is proved, what the project is made of, and
  // the record of what happened. Alphabetical would have been an order too,
  // and a worse one — it puts Architecture beside Capabilities because both
  // start with a letter.
  {
    id: "items", label: "Items", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  // Flows and Runs are two views of one subject: a definition says what a
  // deployment does, a run is one execution of it. They are tabs rather than
  // two destinations because reading a run almost always means reading the
  // definition behind it, and the definition is what an operator opens first.
  {
    id: "deployments", label: "Deployments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    tabs: [
      { id: "flows", label: "Flows" },
      { id: "runs", label: "Runs" },
    ],
  },
  {
    id: "environments", label: "Environments", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "databases", label: "Databases", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-methods", label: "QA methods", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-plans", label: "QA plans", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "qa-activity", label: "QA activity", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "capabilities", label: "Capabilities", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
    pageAction: { label: "Add capability", view: "projects" },
  },
  {
    id: "packs", label: "Packs", scope: SCOPE_NONE,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "architecture", label: "Architecture", scope: SCOPE_SINGLE,
    group: GROUP_DIAGNOSTICS,
  },
  // Fleet-wide traffic, which is not the Inbox: the Inbox is yours.
  {
    id: "messages", label: "Messages", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "launches", label: "Launches", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "events", label: "Events", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "doctor", label: "Doctor", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
  {
    id: "ouroboros", label: "Ouroboros", scope: SCOPE_MULTI,
    group: GROUP_DIAGNOSTICS,
  },
];
