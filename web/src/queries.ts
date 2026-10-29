import type { QueryClient } from "@tanstack/react-query";

/** After a sync, an edit or a rule change, everything read from the ledger may be stale. */
export function invalidateLedger(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: (query) => !["status", "categories"].includes(String(query.queryKey[0])),
  });
}
