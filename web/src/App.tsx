import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LedgerRow } from "./api";
import { TransactionDrawer } from "./components/TransactionDrawer";
import { whenLabel } from "./format";
import { AccountsPage } from "./pages/Accounts";
import { ActivityPage } from "./pages/Activity";
import { OverviewPage } from "./pages/Overview";
import { Link, useRoute, type Route } from "./router";
import { statusRefetchInterval } from "./syncPolling";

const NAV: { route: Route; label: string }[] = [
  { route: "overview", label: "总览" },
  { route: "activity", label: "交易流" },
  { route: "accounts", label: "账户" },
];

export function App() {
  const route = useRoute();
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: (query) => statusRefetchInterval(query.state.data),
  });
  const [selected, setSelected] = useState<LedgerRow | null>(null);
  const closeDrawer = useCallback(() => setSelected(null), []);

  // When a sync finishes, everything read from the ledger is stale.
  const run = status.data?.last_run;
  const runKey = run ? `${run.id}:${run.status}` : null;
  const seenRun = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!status.isSuccess) return;
    if (seenRun.current !== undefined && seenRun.current !== runKey) {
      void queryClient.invalidateQueries({
        predicate: (query) => !["status", "categories"].includes(String(query.queryKey[0])),
      });
    }
    seenRun.current = runKey;
  }, [runKey, status.isSuccess, queryClient]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" />
            <path d="M9 21l5-5 4 3 6-8" />
          </svg>
          <span className="brand-name">Fintrack</span>
        </div>
        <nav aria-label="主导航">
          {NAV.map((item) => (
            <Link key={item.route} to={item.route} className="nav-link" current={item.route === route}>
              {item.label}
            </Link>
          ))}
        </nav>
        {status.data && (
          <div className="sidebar-footer">
            <span className={`env-badge ${status.data.env}`}>{status.data.env === "production" ? "真实账户" : "Sandbox 测试数据"}</span>
            <span>{status.data.syncing ? "正在同步…" : `上次同步 ${whenLabel(status.data.last_success_at)}`}</span>
          </div>
        )}
      </aside>

      <main className="content">
        {status.error && <p className="notice error">连不上 Fintrack 服务：{status.error.message}</p>}
        {route === "overview" && <OverviewPage status={status.data} onSelect={setSelected} />}
        {route === "activity" && <ActivityPage onSelect={setSelected} />}
        {route === "accounts" && <AccountsPage status={status.data} />}
      </main>

      {selected && <TransactionDrawer key={selected.id} row={selected} onClose={closeDrawer} />}
    </div>
  );
}
