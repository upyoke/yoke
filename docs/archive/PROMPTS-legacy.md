# Archived — PROMPTS.md

Evergreen rules moved to `.claude/rules/session.md` and `.claude/rules/accelerated-flow.md`.
These auto-load into every Claude Code session. No more pasting needed.

Historical prompts preserved below for reference.

---

---
GLOBAL CONTEXT:

- **Always check the last bunch of commits in the current repo before moving on**

ALWAYS DOCUMENT THE CURRENT PLAN IN ./BOARD.md (create if missing) SO I CAN RESTART YOU WITHOUT LOSS OF CONTEXT. APPROACH:
- read before you start anything
- document the entire plan in detail in ./BOARD.md before you do anything
- as you perform each step, keep ./BOARD.md updated with everything you did and what the results were
- go step by step and make sure each step tests itself and the whole chain up to that point before moving to next step
- keep increments of work small because context limits are real
- the goal is for you to be able to pick up where you left off if we run out of context tokens and you have to clear the context mid-implementation

- DO NOT INGORE BUGS -- FOUND BUGS ARE VALUABLE -- AT VERY LEAST DOCUMENT IN ./BOARD.md so we can fix later
- DO NOT FIX A BUG WITHOUT FIRST KNOWING WHY AND HOW IT HAPPENED!

- CRITICAL RULE: make sure that everything changed on the remote server is maintained and edited locally, AND ONLY COPIED FROM LATEST HERE TO REMOTE -- NEVER EDIT DIRECTLY ON SERVER
- CRITICAL RULE: Anything you change on the REMOTE server has to be recorded in the spec / installation instructions / documentation in this LOCAL repo! Always do this in the appropriate context, planning, documentation, configuration, code, and all other types of files. We need to be able to easily redeploy the remote app and all of its infra and components instantly, anywhere, at any time, straight from this repo, with no loss of context.

READ NOW NOW NOW: ./README.md

---
CURRENT TASK:

- let's keep working on ./BOARD.md, as we advance the current plan in a continuous improvement cycle: test -> iterate -> update spec/docs/plan -> clear session context -> advance plan. keep the loop tight because we're repeating it hundreds of times. analyze the current state of the plan and get started on the next bite sized chunk, make sure the current ticket is set to ACTIVE while working on it. if you need to split a ticket into tasks / subtasks, then do so, and mark only the one you're tackling as active

Update: we're transitioning from a manual system to a manual system that syncs with yoke

BITE OFF ONLY WHAT YOU KNOW YOU CAN FOR SURE CHEW
- do the most critical bite sized chunk **easily achievable in one session without compacting** and then update ./BOARD.md, ticket, and other docs and commit

pending:
- how can we handle automatically merging similar ideas anytime one is added to the backlog?

---

you're helping me create Yoke. I want you to thoroughly review everything in the ccpm repo __https://github.com/automazeio/ccpm__ and everything in __https://code.claude.com/docs/en/sub-agents__ and __https://code.claude.com/docs/en/sub-agents#example-subagents__
and make sure everything is incorporated that we need from there woven in with what we have and we're not missing anything we should have.

then your mission is to:
- analyze the plan for flaws and tell me the top 10 flaws
- run a simulation of someone installing and using this and telll me the top 5 problems they run into
- give me the top 5 things you would fix
- any other observations or advice

---

add new high priority ticket to the backlog:
- how do we manage the process of transitioning issues from being tracked in BOARD.md in the backlog, not in any sprint, or in a sprint, either active or planned, to the tracked prd -> epics flow? do the epics planned in the backlog sync to PRDs before there is an epic? can this all work without syncing anything to github? what are the benefits of syncing? can we test that those are working?
- actually what probably makes sense it to remove the concept of sprints and just plan epics with tasks in the backlog, no?
- let's plan this ticket before you add it
- this is how i think maybe it should work:
    - within a yoke repo, there is a numbering system for all epics and issues
    - this is regardless of whether it starts life as a prd created through yoke, or whether it starts life as un unsynced item manually added to CURRENT-=PLAN.md not through yoke -- all ideas need to go in as epics and issues
    - when we do sync to github, those numbers dont change. the ones that sync to github are kept in sync, and the ones that have never been synced stay in BOARD.md
    - when a prd is created, it uses the same tracking entry and id as the epic idea it came from, if there is one in there that mnatches pretty well or is explicitly supplied
    - how far is what we have today from this?
- i want to make this entire process a first class yoke citizen. what does that mean to you?


---
SIMULATION

- let's prep for real world ops and harden the app by running a full operator + app lifecycle simulation. log it to ./SIMULATION.md (erase currect file if it exists, and start from scratch). simulate my input when needed. start out with how i would install it on a brand new VPS and then run it for the first time. don't skip steps. ensure that the operator has all functionality they need to do their job, change settings, adapt context, and tweak the system

- when a command, action, or event occurs in the simulation, trace all the resulting paths that happen in the system to identify where things might get stuck or have unexpected results

- when encountering a gap, log it at the bottom of ./SIMULATION.md and move on. our goal is to capture the gaps we'll run into in the real world anyway and fix them before we do. **include critical context you already have that will save time and make us smarter next session, when we address these gaps.**

- example gaps:
    - "oops, nothing actually ever triggers that"
    - "oops, when we try to do x, we won't have access to y"
    - "oops, we totally forgot to consider z"
    - "oops, that's totally going to error out"
    - "oops, we never installed a necessary dependency"
    - "oops, there's an obvious bug in the code"
    - "oops, we're referring to different variable names when they need to match"
    - etc...

- we've run a simulation, and it's time to all gaps identified in ./SIMULATION.md, and organize a Remediation Plan in ./BOARD.md with themes and stages in preparation for execution.
- chunk and sequence out the work starting from the most fundamental/critical theme.
