/**
 * What a host passes the shared Team page under `capabilities.data.team`.
 *
 * Team reads it once at mount. An absent or malformed fact draws Team as it
 * is without a host. A host's seat display itself is Team's `beforeScope`
 * section, which leads the page above Invites.
 */
export interface UniverseTeamHost {
  /**
   * Seats the organization can still fill, a non-negative integer. When the
   * viewer can invite, the Invites header shows it and the invite form says
   * the invite uses one of them; at 0 the form says no seats are left and
   * names Billing and revoking a pending invite as the way out. Absent or `null` means the host has no seat
   * limit to report.
   */
  readonly seatsLeft?: number | null;
}
