import type { Status } from "./api";

// A sync triggered from the UI starts on the server a moment after the request returns,
// so for a short while poll fast even before /api/status reports it as running.
let fastUntil = 0;

export function expectSync(): void {
  fastUntil = Date.now() + 20_000;
}

/** How often to refresh /api/status: fast while a sync or a new bank's backfill is under way. */
export function statusRefetchInterval(status: Status | undefined): number {
  const busy =
    status?.syncing ||
    status?.items.some((item) => item.status === "active" && item.transactions_status !== "HISTORICAL_UPDATE_COMPLETE");
  return busy || Date.now() < fastUntil ? 2_500 : 60_000;
}
