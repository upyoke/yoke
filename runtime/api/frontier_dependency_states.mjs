// The six Frontier states the dependency graph must draw correctly, as test
// fixtures. "today" is the production Frontier of 7 October 2026, read from
// a capture of the served page: every Waiting card named its one blocker and
// carried that edge's rationale, and every live edge was activation +
// fact:merged. The other states exercise what production on any one day does
// not: scale, every gate and condition, stuck and broken chains, a wide
// fan-out, and nothing waiting. Their items are plausible, not real.
//
// Node: [ref, band, stage, title, {held, claim, deploy, envs}]. Edge:
// [blocker, dependent, gate, satisfaction], defaulting to activation +
// fact:merged; `why` holds each edge's rationale, keyed "blocker>dependent".
// A node with no edge renders only in its band.

import { frontierIndex } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_dependency_model.js";

const FRONTIER_STATE_SMALL_CHAINS=[
  ['YOK-3920','active','implementing','Sessions page filters by harness'],['YOK-3921','waiting','idea','Saved session filters'],
  ['YOK-3922','release','release','Inbox marks messages read on open'],['YOK-3923','waiting','idea','Inbox unread count in the tab title'],
  ['PLAT-230','active','reviewing-implementation','Billing page shows seat usage'],['PLAT-231','waiting','idea','Seat usage alert at 90%'],
  ['YOK-3924','ready','idea','Doctor groups checks by owner'],['YOK-3925','waiting','idea','Doctor owner filter'],
  ['BUZ-150','active','implementing','Buzz exports the theme token file'],['YOK-3926','waiting','idea','Yoke imports Buzz theme tokens'],
  ['YOK-3927','active','implementing','Launch records the reasoning effort'],['YOK-3928','waiting','idea','Sessions card shows reasoning effort'],
];

export const FRONTIER_STATES=[
 {id:'today',label:'Today — captured production',
  nodes:[
   ["PLAT-143", "waiting", "implementing", "Prototype cost and performance diagnostics with verified data", {"held": "Frozen", "claim": "codex-desktop · stale"}],
   ["PLAT-188", "waiting", "idea", "Copy the settled installation rules block from yoke"],
   ["YOK-3758", "waiting", "idea", "Settle the shared installation rules block and add Platform DB reads"],
   ["YOK-3721", "waiting", "idea", "Default level per workflow stage binding"],
   ["YOK-3720", "waiting", "idea", "Staff by level and show level capacity in steering"],
   ["YOK-3719", "waiting", "idea", "Launch workers by level with quota-aware placement"],
   ["YOK-3718", "waiting", "idea", "Store levels as universe defaults with project overrides"],
   ["YOK-3725", "waiting", "idea", "Validate every stored emoji and glyph against the glyph contract"],
   ["YOK-3723", "waiting", "idea", "Build the Settings Levels page from the prototype"],
   ["YOK-3722", "waiting", "idea", "Model refresh proposes level changes"],
   ["PLAT-190", "active", "implementing", "Prototype Frontier alternatives that show Waiting as a dependency graph", {"claim": "claude-desktop · parked"}],
   ["YOK-3759", "active", "reviewing implementation", "Browser QA identity uses the carried project's delivered commit", {"claim": "claude-cli · active"}],
   ["YOK-3757", "active", "reviewing implementation", "Teach db-admin connections only in the source-dev layer", {"claim": "codex-cli · active"}],
   ["YOK-3756", "active", "reviewing implementation", "Document seats drain parked mail from linked items in any project", {"claim": "claude-cli · stale"}],
   ["YOK-3754", "active", "reviewing implementation", "Refuse a stale bound source before dispatching the release", {"claim": "claude-cli · parked"}],
   ["YOK-3755", "active", "implementing", "QA cases declare target environments; done waits for each", {"claim": "codex-cli · parked"}],
   ["YOK-3727", "active", "implementing", "Re-pin open items off advance-bound workflow versions before 0053", {"claim": "claude-cli · parked"}],
   ["YOK-3717", "active", "implementing", "Rename execution lanes to levels", {"claim": "claude-cli · parked"}],
   ["YOK-3702", "active", "implementing", "Pass only public item refs through clients and stored keys", {"claim": "codex-cli · parked"}],
   ["PLAT-189", "release", "release", "Prove cloud connect approval on Stage for PLAT-177", {"claim": "codex-cli · parked"}],
   ["PLAT-187", "release", "release", "Org admins can change a member's role", {"claim": "claude-cli · parked"}],
   ["PLAT-183", "release", "release", "Platform signed-in screens record page views", {"claim": "claude-cli · parked"}],
   ["PLAT-178", "release", "release", "Hosted public pages track page views and signup attribution", {"claim": "codex-cli · active"}],
   ["YOK-3753", "release", "release", "CI-gated release create reads private repos with a scoped token", {"claim": "claude-cli · parked"}],
   ["YOK-3752", "release", "release", "Stale bound-source failures say a new run is required", {"claim": "claude-cli · parked"}],
   ["YOK-3645", "release", "release", "Restore full Doctor check coverage without the tracer", {"claim": "codex-cli · active"}],
   ["PLAT-181", "release", "release", "Platform stage release runs admit stage-targeted item QA", {"claim": "claude-cli · parked"}],
   ["YOK-3750", "done", "done", "Never kill a resuming worker; report idle workers truthfully"],
   ["YOK-3751", "done", "done", "Test-machine missions use the host's own browser when Yoke is absent"],
   ["PLAT-177", "done", "done", "Cloud machine approval uses the shared workbench approval page"],
   ["PLAT-185", "done", "done", "Adopt structured-events 4.0.0 on Platform"],
   ["YOK-3749", "done", "done", "Installed skills never link to Yoke-repo-only docs"],
   ["YOK-3748", "done", "done", "Test-machine QA prep never needs Yoke on the host"],
   ["YOK-3716", "done", "done", "Workbench follows host-owned analytics consent"],
   ["YOK-3709", "done", "done", "Verified attribution read and cross-origin sign-in hand-off"]],
  why:{"YOK-3758>PLAT-188": "Companion: the platform copy takes the exact text the yoke item merges.",
   "YOK-3757>YOK-3758": "Both edit this repo's CLAUDE.md/AGENTS.md; settle the installation block after YOK-3757 moves db-admin teaching out of the managed block.",
   "YOK-3720>YOK-3721": "Binding default level edits the same launch path and steer skill text; serialize after it",
   "YOK-3719>YOK-3720": "Steering report and skill teach the level launch that must exist first",
   "YOK-3718>YOK-3719": "Launch by level reads level options from universe storage",
   "YOK-3717>YOK-3718": "Universe level storage builds on the renamed level columns and settings keys",
   "YOK-3717>YOK-3725": "The lanes-to-levels rename touches the glyph contract module and its callers; generalize it after the rename lands",
   "YOK-3718>YOK-3723": "Levels page reads universe level storage",
   "YOK-3718>YOK-3722": "Refresh proposes changes to stored level options"},
  edges:[["YOK-3758", "PLAT-188"], ["YOK-3757", "YOK-3758"], ["YOK-3720", "YOK-3721"], ["YOK-3719", "YOK-3720"], ["YOK-3718", "YOK-3719"], ["YOK-3717", "YOK-3718"], ["YOK-3717", "YOK-3725"], ["YOK-3718", "YOK-3723"], ["YOK-3718", "YOK-3722"]]},

 {id:'busy',label:'Busy week — scale, fan-in, diamonds',
  blurb:'Four chains and 22 waiting items. One chain is six steps deep, two items wait on two blockers each, and one root nobody has started holds four items back.',
  nodes:[
   ['YOK-3801','active','implementing','Typed release manifest replaces the YAML pin file',{claim:'codex-cli · active'}],
   ['YOK-3790','active','reviewing-implementation','Session wake contract moves into the harness manifest',{claim:'claude-cli · active'}],
   ['PLAT-201','release','release','Tenant boxes read the typed release manifest',{deploy:'stage ✓ · prod deploying',envs:['stage','prod']}],
   ['YOK-3760','ready','idea','QA cases record their target environment'],
   ['BUZ-140','active','implementing','Buzz shares the session card component',{claim:'cursor-cli · active'}],
   ['YOK-3802','waiting','idea','Release bridge writes the typed manifest'],
   ['YOK-3803','waiting','idea','Doctor checks that the manifest and pin agree'],
   ['PLAT-202','waiting','idea','Promote workflow reads the typed manifest'],
   ['YOK-3804','waiting','idea','Remove the YAML pin parser'],
   ['PLAT-203','waiting','idea','Retire the pin-file drift alarm'],
   ['YOK-3805','waiting','idea','Charge ranks by manifest readiness'],
   ['YOK-3806','waiting','idea','Release notes are generated from the manifest'],
   ['YOK-3807','waiting','idea','Document the manifest schema'],
   ['YOK-3808','waiting','idea','Release review shows the manifest diff'],
   ['YOK-3809','waiting','idea','Rollback picks a manifest, not a commit'],
   ['PLAT-204','waiting','idea','Fleet dashboard shows the manifest on each box'],
   ['YOK-3791','waiting','idea','Cursor adopts the manifest wake contract'],
   ['YOK-3792','waiting','idea','Codex records an explicit no-wake deferral'],
   ['YOK-3793','waiting','idea','Steering reads wake capability from the manifest'],
   ['YOK-3794','waiting','idea','Doctor checks wake capability per harness'],
   ['YOK-3761','waiting','idea','QA plans pick cases by environment'],
   ['YOK-3762','waiting','idea','Stage QA runs only stage-targeted cases'],
   ['PLAT-205','waiting','idea','Platform stage flow runs targeted QA'],
   ['YOK-3763','waiting','idea','QA activity filters by environment'],
   ['YOK-3795','waiting','idea','Yoke dashboard adopts the shared session card'],
   ['PLAT-206','waiting','idea','Hosted dashboard ships the shared session card'],
   ['YOK-3770','waiting','idea','Record per-session token usage',{held:'Frozen'}],
   ['YOK-3811','active','implementing','Relay retries on reconnect',{claim:'codex-cli · active'}],
   ['YOK-3812','release','release','Doctor quick mode finishes under ten seconds',{deploy:'prod ✓ · QA running'}],
   ['YOK-3780','done','done','Machines page shows idle time'],
  ],
  why:{'YOK-3801>YOK-3802':'The bridge writes the manifest format this item defines.',
   'YOK-3802>YOK-3803':'Doctor compares the pin with a manifest the bridge has actually written.',
   'YOK-3801>PLAT-202':'Promote reads the typed manifest, so the type has to exist first.',
   'PLAT-201>PLAT-202':'Promote must not read manifests until every tenant box can parse them in production.',
   'YOK-3802>YOK-3804':'The YAML parser stays until nothing writes YAML pins.',
   'PLAT-202>YOK-3804':'Platform promote is the last YAML reader; remove the parser after it switches.',
   'PLAT-202>PLAT-203':'The drift alarm watches the pin file promote stops writing.',
   'YOK-3803>YOK-3805':'Readiness ranking uses the agreement check Doctor adds.',
   'YOK-3803>YOK-3806':'Notes generation reuses the manifest reader Doctor introduces.',
   'YOK-3804>YOK-3807':'Document the schema once the YAML form is gone.',
   'YOK-3807>YOK-3808':'The diff view renders the documented schema fields.',
   'YOK-3808>YOK-3809':'Rollback picks from the same manifest diff list.',
   'YOK-3809>PLAT-204':'The fleet view links each box to its rollback target.',
   'YOK-3790>YOK-3791':'Cursor adopts the contract fields this item adds to the manifest.',
   'YOK-3790>YOK-3792':'The deferral is recorded in the contract this item defines.',
   'YOK-3791>YOK-3793':'Steering needs every harness on the contract before it reads it.',
   'YOK-3792>YOK-3793':'Steering needs every harness on the contract before it reads it.',
   'YOK-3793>YOK-3794':'Doctor checks the capability steering now relies on.',
   'YOK-3760>YOK-3761':'Plans select on the target environment field this item adds.',
   'YOK-3760>YOK-3762':'Stage QA filters on the target environment field.',
   'YOK-3762>PLAT-205':'Platform stage flow calls the targeted QA run.',
   'YOK-3760>YOK-3763':'The activity filter needs the recorded environment.',
   'BUZ-140>YOK-3795':'Yoke imports the component Buzz publishes.',
   'YOK-3795>PLAT-206':'Hosted ships the Yoke build that carries the shared card.'},
  edges:[['YOK-3801','YOK-3802'],['YOK-3802','YOK-3803'],['YOK-3801','PLAT-202'],['PLAT-201','PLAT-202','activation','fact:deployed:prod'],
   ['YOK-3802','YOK-3804'],['PLAT-202','YOK-3804'],['PLAT-202','PLAT-203'],['YOK-3803','YOK-3805'],['YOK-3803','YOK-3806'],
   ['YOK-3804','YOK-3807'],['YOK-3807','YOK-3808'],['YOK-3808','YOK-3809'],['YOK-3809','PLAT-204'],
   ['YOK-3790','YOK-3791'],['YOK-3790','YOK-3792'],['YOK-3791','YOK-3793'],['YOK-3792','YOK-3793'],['YOK-3793','YOK-3794'],
   ['YOK-3760','YOK-3761'],['YOK-3760','YOK-3762'],['YOK-3762','PLAT-205'],['YOK-3760','YOK-3763'],
   ['BUZ-140','YOK-3795'],['YOK-3795','PLAT-206']]},

 {id:'gates',label:'Every gate and condition',
  blurb:'Start, merge and close gates side by side. Clears on merge, on reaching a stage, on done, and on being live in an environment. Items you can build now still show what they must merge after.',
  nodes:[
   ['YOK-3820','active','implementing','Workflow versions carry gate definitions',{claim:'codex-cli · active'}],
   ['YOK-3821','active','implementing','Workflows page shows gate definitions',{claim:'claude-cli · active'}],
   ['YOK-3826','ready','idea','CLI help lists each workflow’s gates'],
   ['YOK-3822','waiting','idea','Operators edit gates in the web UI'],
   ['YOK-3824','waiting','idea','Document the gate editor'],
   ['YOK-3827','active','reviewing-implementation','Gate evaluation returns structured reasons',{claim:'codex-cli · parked'}],
   ['YOK-3828','waiting','idea','Denials quote the failing gate'],
   ['PLAT-210','release','release','Hosted tenants converge the gate table',{deploy:'stage ✓ · prod not yet',envs:['stage','prod']}],
   ['PLAT-211','waiting','idea','Org admins see gate history'],
   ['YOK-3823','release','release','Gate QA case on hosted tenants',{deploy:'prod ✓ · QA passed'}],
  ],
  why:{'YOK-3820>YOK-3821':'Build the page against the draft schema; land it after the schema merges.',
   'YOK-3820>YOK-3826':'Help text can be written now but must ship with the merged gate names.',
   'YOK-3820>YOK-3822':'The editor needs gate definitions released and closed out, not just merged.',
   'YOK-3822>YOK-3824':'Document the editor once it reaches release and stops changing.',
   'YOK-3827>YOK-3828':'Denials quote the structured reasons once they are released.',
   'PLAT-210>PLAT-211':'Gate history reads the converged table on production tenants.',
   'PLAT-210>YOK-3823':'The QA case passed; the item closes once the table is live on prod.'},
  edges:[['YOK-3820','YOK-3821','integration','fact:merged'],['YOK-3820','YOK-3826','integration','fact:merged'],
   ['YOK-3820','YOK-3822','activation','status:done'],['YOK-3822','YOK-3824','activation','status:release'],
   ['YOK-3827','YOK-3828','activation','status:release'],
   ['PLAT-210','PLAT-211','activation','fact:deployed:prod'],['PLAT-210','YOK-3823','closure','fact:deployed:prod']]},

 {id:'stuck',label:'Stuck, broken and cross-project',
  blurb:'Chains that cannot move: a frozen root, a blocked root, a cancelled blocker, a deploy target outside the blocker’s flow, and a deadlock. A Buzz blocker stays visible when you filter to PLAT, because a PLAT item waits on it.',
  nodes:[
   ['YOK-3830','waiting','idea','Move session identity into the relay',{held:'Frozen by ben'}],
   ['YOK-3831','waiting','idea','Relay owns session revival'],['YOK-3832','waiting','idea','Drop the process-anchor registry'],
   ['YOK-3833','waiting','idea','Sessions page reads identity from the relay'],
   ['YOK-3840','off','cancelled','Rewrite the auth relay in Go'],['YOK-3841','waiting','idea','Relay sign-in uses device codes'],
   ['PLAT-220','release','release','Billing webhooks verify signatures',{deploy:'stage ✓ · flow ends at stage',envs:['stage']}],
   ['PLAT-221','waiting','idea','Invoices show webhook delivery status'],
   ['YOK-3850','waiting','idea','Route models through Bedrock',{held:'Blocked — waiting on an AWS quota increase'}],
   ['YOK-3851','waiting','idea','Fable runs through Bedrock'],['YOK-3852','waiting','idea','Bedrock cost appears on session cards'],
   ['YOK-3860','waiting','idea','Doctor reads its check registry from the database'],
   ['YOK-3861','waiting','idea','The check registry seeds from Doctor modules'],
   ['YOK-3862','waiting','idea','Doctor lists checks by owner'],
   ['BUZ-90','active','implementing','Shared theme tokens',{claim:'cursor-cli · active'}],
   ['PLAT-225','waiting','idea','Hosted app reads Buzz theme tokens'],
   ['YOK-3880','active','implementing','Machines page groups by owner',{claim:'codex-cli · active'}],
   ['YOK-3881','waiting','idea','Machines owner filter'],
  ],
  why:{'YOK-3830>YOK-3831':'Revival moves into the relay with the identity it restores.',
   'YOK-3830>YOK-3832':'The anchor registry is the identity source this item replaces.',
   'YOK-3831>YOK-3833':'The page reads identity from wherever revival keeps it.',
   'YOK-3840>YOK-3841':'Device codes were designed for the Go relay.',
   'PLAT-220>PLAT-221':'Invoices show delivery status only from production webhooks.',
   'YOK-3850>YOK-3851':'Fable routing needs the Bedrock quota first.',
   'YOK-3850>YOK-3852':'Cost appears once calls actually route through Bedrock.',
   'YOK-3860>YOK-3861':'Seeding writes the table Doctor reads.',
   'YOK-3861>YOK-3860':'Doctor must read the seeded table before seeding is trusted.',
   'YOK-3861>YOK-3862':'Owners come from the seeded registry.',
   'BUZ-90>PLAT-225':'The hosted app reads tokens from the Buzz package.',
   'YOK-3880>YOK-3881':'The filter groups by the owner field this item adds.'},
  edges:[['YOK-3830','YOK-3831'],['YOK-3830','YOK-3832'],['YOK-3831','YOK-3833'],
   ['YOK-3840','YOK-3841'],['PLAT-220','PLAT-221','activation','fact:deployed:prod'],
   ['YOK-3850','YOK-3851'],['YOK-3850','YOK-3852'],
   ['YOK-3860','YOK-3861'],['YOK-3861','YOK-3860'],['YOK-3861','YOK-3862'],
   ['BUZ-90','PLAT-225'],['YOK-3880','YOK-3881']]},

 {id:'wide',label:'Wide — big fan-out, many small chains',
  blurb:'One root holds back fourteen items directly, beside six unrelated two-item chains. Tests a tall column and a long list of roots.',
  nodes:[['YOK-3900','active','implementing','Function registry declares minimum serving versions',{claim:'codex-cli · active'}],
   ...['items','claims','sessions','lifecycle','qa','doctor','deploy','packs','strategy','events','inbox','machines','workflows','github']
     .map((area,i)=>[`YOK-${3901+i}`,'waiting','idea',`${area[0].toUpperCase()+area.slice(1)} functions declare a serving floor`]),
   ...FRONTIER_STATE_SMALL_CHAINS],
  why:Object.fromEntries([...Array.from({length:14},(_,i)=>[`YOK-3900>YOK-${3901+i}`,'Each area declares its floor in the registry field YOK-3900 adds.']),
   ...Array.from({length:6},(_,i)=>[`${FRONTIER_STATE_SMALL_CHAINS[i*2][0]}>${FRONTIER_STATE_SMALL_CHAINS[i*2+1][0]}`,'Builds on what the first item ships.'])]),
  edges:[...Array.from({length:14},(_,i)=>['YOK-3900',`YOK-${3901+i}`]),
   ...Array.from({length:6},(_,i)=>[FRONTIER_STATE_SMALL_CHAINS[i*2][0],FRONTIER_STATE_SMALL_CHAINS[i*2+1][0]])]},

 {id:'empty',label:'Nothing waiting',
  blurb:'No item waits on another and nothing is held. The section says so in one line, like Ready does today.',
  nodes:[['YOK-3950','active','implementing','Inbox search matches message bodies',{claim:'claude-cli · active'}],
   ['YOK-3951','release','release','Doctor flags stale worktrees',{deploy:'stage ✓ · prod deploying'}],
   ['PLAT-240','done','done','Members page sorts by last active']],
  edges:[]},
];

const TERMINAL_STAGES = new Set(["cancelled", "stopped", "failed"]);

// A state as the model the Frontier builds from served rows: an edge waiting
// on an environment carries whether the blocker's flow reaches it, and an
// item not on the Frontier that was cancelled or stopped is dead.
export function stateModel(state) {
  const nodes = new Map(state.nodes.map(([ref, band, stage, title, o = {}]) => [ref, {
    ref, band, stage, title, href: `/items/${ref}`, projectId: ref.split("-")[0],
    dead: band === "off" && TERMINAL_STAGES.has(stage), ...o,
  }]));
  const edges = state.edges.map(([from, to, gate = "activation", sat = "fact:merged"]) => {
    const env = sat.startsWith("fact:deployed:") ? sat.slice(14) : null;
    const envs = nodes.get(from)?.envs;
    return {
      from, to, gate, sat, why: state.why?.[`${from}>${to}`] || "",
      env: env && { name: env, delivery_state: "not deployed", in_delivery_flow: !envs || envs.includes(env) },
    };
  });
  return frontierIndex(nodes, edges);
}

export function state(id) {
  return FRONTIER_STATES.find((entry) => entry.id === id);
}
