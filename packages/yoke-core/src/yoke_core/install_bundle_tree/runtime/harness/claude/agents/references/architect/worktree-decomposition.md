## Worktree Decomposition

Read after the shared-file analysis, before grouping tasks into lanes. Conduct
runs one Engineer per active lane in parallel, so fan out by default.

1. Partition tasks into the largest groups whose internal order is satisfiable
   and whose combined edit scopes are disjoint. An attested `coordination_only`
   overlap (additive settings, different functions) does not join two lanes.
2. Find the foundation: output the other groups consume through a live
   registry, data, migration, packet or imported module. It lands first, and
   each consumer carries a cross-lane activation dependency on it.
3. One lane needs a structural reason: a linear live dependency chain,
   dependent same-hunk edits, or a tiny epic (three tasks or fewer) whose lane
   overhead exceeds the saving. A shared claim or convenience is not a reason.
4. With path claims enabled, each lane registers its own complete claim; one
   epic-wide claim never stands in for independent lanes.
