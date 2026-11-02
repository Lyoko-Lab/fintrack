import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type ActivityFilters, type Cursor, type FlowType, type LedgerRow } from "../api";
import { CategorySelect } from "../components/CategorySelect";
import { TransactionList } from "../components/TransactionList";
import { rangeLabel } from "../format";
import { useI18n } from "../i18n";
import { ROUTES } from "../router";

const FLOW_TYPES: FlowType[] = ["expense", "income", "transfer"];

/** Filters another page can open this one with, e.g. /activity?category=dining&from=2026-10-01&to=2026-10-28. */
function linkedFilters() {
  const params = new URLSearchParams(window.location.search);
  const [from, to] = [params.get("from"), params.get("to")];
  return { categoryId: params.get("category") ?? "", range: from && to ? { from, to } : null };
}

export function ActivityPage({ onSelect }: { onSelect(row: LedgerRow): void }) {
  const { t } = useI18n();
  const [linked] = useState(linkedFilters);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [accountId, setAccountId] = useState("");
  const [categoryId, setCategoryId] = useState(linked.categoryId);
  const [flowType, setFlowType] = useState<FlowType | "">("");
  const [range, setRange] = useState(linked.range);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: Infinity });
  const filters: ActivityFilters = {
    q: query || undefined,
    account_id: accountId ? Number(accountId) : undefined,
    category_id: categoryId || undefined,
    flow_type: flowType || undefined,
    date_from: range?.from,
    date_to: range?.to,
  };
  const feed = useInfiniteQuery({
    queryKey: ["activity", "feed", filters],
    queryFn: ({ pageParam }) => api.activity(filters, pageParam),
    initialPageParam: null as Cursor | null,
    getNextPageParam: (page) => page.next,
  });

  const rows = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = Boolean(query || accountId || categoryId || flowType || range);
  const reset = () => {
    setSearch("");
    setQuery("");
    setAccountId("");
    setCategoryId("");
    setFlowType("");
    setRange(null);
    window.history.replaceState(null, "", ROUTES.activity);
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>{t.activity.title}</h1>
          <p className="page-subtitle">{t.activity.subtitle}</p>
        </div>
      </header>

      <div className="filters" role="search">
        <input
          type="search"
          placeholder={t.activity.search}
          aria-label={t.activity.searchLabel}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          aria-label={t.activity.type}
          value={flowType}
          onChange={(event) => setFlowType(event.target.value as FlowType | "")}
        >
          <option value="">{t.activity.allTypes}</option>
          {FLOW_TYPES.map((flow) => (
            <option key={flow} value={flow}>
              {t.flow[flow]}
            </option>
          ))}
        </select>
        <select aria-label={t.activity.account} value={accountId} onChange={(event) => setAccountId(event.target.value)}>
          <option value="">{t.activity.allAccounts}</option>
          {accounts.data?.map((account) => (
            <option key={account.id} value={account.id}>
              {account.institution_name} · {account.name}
              {account.mask ? ` ··${account.mask}` : ""}
            </option>
          ))}
        </select>
        <CategorySelect
          categories={categories.data ?? []}
          value={categoryId}
          onChange={setCategoryId}
          allowGroups
          placeholder={t.activity.allCategories}
          label={t.activity.category}
        />
        {range && (
          <span className="filter-chip">
            {rangeLabel(range.from, range.to)}
            <button type="button" aria-label={t.activity.clearDates} onClick={() => setRange(null)}>
              ×
            </button>
          </span>
        )}
        {filtered && (
          <button type="button" onClick={reset}>
            {t.activity.clear}
          </button>
        )}
      </div>

      <section className="panel">
        {feed.error && <p className="notice error">{feed.error.message}</p>}
        {rows.length > 0 ? (
          <TransactionList rows={rows} onSelect={onSelect} />
        ) : (
          <p className="empty">{feed.isPending ? t.common.loading : filtered ? t.activity.noMatches : t.common.noTransactions}</p>
        )}
        {feed.hasNextPage && (
          <button
            type="button"
            className="load-more"
            disabled={feed.isFetchingNextPage}
            onClick={() => void feed.fetchNextPage()}
          >
            {feed.isFetchingNextPage ? t.common.loading : t.activity.loadMore}
          </button>
        )}
      </section>
    </>
  );
}
