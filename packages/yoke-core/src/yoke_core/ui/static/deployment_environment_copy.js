// What a view says where a deployment environment should be named and
// none is. Run cards, the item delivery panels, and the QA execution
// target view all render that same absence, so they read the wording
// from here rather than each carrying its own copy of the phrase.

// Shown in place of an environment name. It reports what the record
// holds — no environment is named — rather than diagnosing why, which
// the reader of a card cannot act on and which "unavailable" wrongly
// implies is a transient failure to reach one.
export const NO_ENVIRONMENT_LABEL = "no environment";
