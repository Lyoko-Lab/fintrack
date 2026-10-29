import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type ActivityFilters, type Cursor, type FlowType, type LedgerRow } from "../api";
import { CategorySelect } from "../components/CategorySelect";
import { TransactionList } from "../components/TransactionList";
import { rangeLabel } from "../format";
import { ROUTES } from "../router";

/** Filters another page can open this one with, e.g. /activity?category=dining&from=2026-10-01&to=2026-10-28. */
function linkedFilters() {
  const params = new URLSearchParams(window.location.search);
  const [from, to] = [params.get("from"), params.get("to")];
  return { categoryId: params.get("category") ?? "", range: from && to ? { from, to } : null };
}

export function ActivityPage({ onSelect }: { onSelect(row: LedgerRow): void }) {
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
          <h1>交易流</h1>
          <p className="page-subtitle">所有账户的交易合在一起，按日期排列。转账照常显示，但不计入收支。</p>
        </div>
      </header>

      <div className="filters" role="search">
        <input
          type="search"
          placeholder="搜索商户、银行描述或备注"
          aria-label="搜索交易"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select aria-label="类型" value={flowType} onChange={(event) => setFlowType(event.target.value as FlowType | "")}>
          <option value="">全部类型</option>
          <option value="expense">支出</option>
          <option value="income">收入</option>
          <option value="transfer">转账</option>
        </select>
        <select aria-label="账户" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
          <option value="">全部账户</option>
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
          placeholder="全部分类"
          label="分类"
        />
        {range && (
          <span className="filter-chip">
            {rangeLabel(range.from, range.to)}
            <button type="button" aria-label="不限日期" onClick={() => setRange(null)}>
              ×
            </button>
          </span>
        )}
        {filtered && (
          <button type="button" onClick={reset}>
            清除筛选
          </button>
        )}
      </div>

      <section className="panel">
        {feed.error && <p className="notice error">{feed.error.message}</p>}
        {rows.length > 0 ? (
          <TransactionList rows={rows} onSelect={onSelect} />
        ) : (
          <p className="empty">{feed.isPending ? "加载中…" : filtered ? "没有符合条件的交易" : "还没有交易"}</p>
        )}
        {feed.hasNextPage && (
          <button
            type="button"
            className="load-more"
            disabled={feed.isFetchingNextPage}
            onClick={() => void feed.fetchNextPage()}
          >
            {feed.isFetchingNextPage ? "加载中…" : "加载更多"}
          </button>
        )}
      </section>
    </>
  );
}
