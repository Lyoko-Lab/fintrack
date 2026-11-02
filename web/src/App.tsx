import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LedgerRow } from "./api";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { TransactionDrawer } from "./components/TransactionDrawer";
import { whenLabel } from "./format";
import { useI18n } from "./i18n";
import { AccountsPage } from "./pages/Accounts";
import { ActivityPage } from "./pages/Activity";
import { InsightsPage } from "./pages/Insights";
import { OverviewPage } from "./pages/Overview";
import { RulesPage } from "./pages/Rules";
import { invalidateLedger } from "./queries";
import { Link, useRoute, useScrollRestoration, type Route } from "./router";
import { statusRefetchInterval } from "./syncPolling";

const NAV: Route[] = ["overview", "activity", "insights", "rules", "accounts"];

export function App() {
  // Reading the language here renders the whole app again when it changes, labels formatted
  // outside components (format.ts) included.
  const { t } = useI18n();
  const route = useRoute();
  useScrollRestoration();
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
    if (seenRun.current !== undefined && seenRun.current !== runKey) void invalidateLedger(queryClient);
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
        <nav aria-label={t.nav.label}>
          {NAV.map((item) => (
            <Link key={item} to={item} className="nav-link" current={item === route}>
              {t.nav[item]}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          {status.data && (
            <div className="sync-status">
              <span className={`env-badge ${status.data.env}`}>{t.shell.env[status.data.env]}</span>
              <span>{status.data.syncing ? t.sync.running : t.sync.last(whenLabel(status.data.last_success_at))}</span>
            </div>
          )}
          <LanguageSwitch />
        </div>
      </aside>

      <main className="content">
        {status.error && <p className="notice error">{t.shell.unreachable(status.error.message)}</p>}
        {route === "overview" && <OverviewPage status={status.data} onSelect={setSelected} />}
        {route === "activity" && <ActivityPage onSelect={setSelected} />}
        {route === "insights" && <InsightsPage />}
        {route === "rules" && <RulesPage />}
        {route === "accounts" && <AccountsPage status={status.data} />}
      </main>

      {selected && <TransactionDrawer key={selected.id} row={selected} onClose={closeDrawer} />}
    </div>
  );
}
