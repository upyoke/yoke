/** Normalize qualified RFC3339 without dropping database microseconds. */
export declare function formatInstant(value: string): string;
/** PostgreSQL's qualified text encoding is an adapter, never stored wire form. */
export declare function formatDatabaseInstant(value: string): string;
/** Preserve exact microseconds for comparisons; convert to Date only for display. */
export declare function instantMicros(value: string): bigint;
/** A Date producer measured milliseconds; trailing zeros add no precision. */
export declare function instantFromDate(value: Date): string;
