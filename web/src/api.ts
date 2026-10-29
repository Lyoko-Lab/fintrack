// Typed client for the Fintrack API (src/fintrack/app.py). Money is always integer cents,
// signed from the owner's point of view: money in > 0, money out < 0.

export type FlowType = "income" | "expense" | "transfer";
export type ItemStatus = "active" | "login_required" | "error";
export type Granularity = "day" | "week" | "month" | "year";
export type CompareMode = "previous" | "year" | "average";
export type MatchField = "merchant" | "description";
export type Direction = "inflow" | "outflow";

export interface Item {
  id: number;
  institution_name: string | null;
  status: ItemStatus;
  transactions_status: string | null;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface SyncRun {
  id: number;
  triggered_by: string;
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
}

export interface Status {
  env: "sandbox" | "production";
  plaid_configured: boolean;
  syncing: boolean;
  items: Item[];
  last_run: SyncRun | null;
  last_success_at: string | null;
}

export interface Account {
  id: number;
  item_id: number;
  name: string;
  official_name: string | null;
  mask: string | null;
  type: string;
  subtype: string | null;
  current_cents: number | null;
  available_cents: number | null;
  limit_cents: number | null;
  balance_as_of: string | null;
  institution_name: string | null;
}

export interface Comparison {
  current: number;
  previous: number;
}

export interface Period {
  start: string;
  end: string;
}

export interface Overview {
  today: string;
  period: Period;
  previous_period: Period;
  income: Comparison;
  spending: Comparison;
  net_cash: Comparison & { cash: number; debt: number; as_of: string | null };
}

export interface LedgerRow {
  id: number;
  transaction_date: string;
  posted_date: string;
  pending: number;
  amount_cents: number;
  display_name: string | null;
  merchant_name: string | null;
  description: string | null;
  original_description: string | null;
  logo_url: string | null;
  pfc_detailed: string | null;
  account_id: number;
  account_name: string;
  account_mask: string | null;
  account_type: string;
  institution_name: string | null;
  category_id: string | null;
  category_name: string | null;
  category_group: string | null;
  flow_type: FlowType | null;
  category_edited: number;
  category_rule: string | null;
  user_rule_id: number | null;
  user_rule_field: MatchField | null;
  user_rule_pattern: string | null;
  transfer_peer_id: number | null;
  peer_account_name: string | null;
  peer_account_mask: string | null;
  note: string | null;
}

export interface Cursor {
  before: string;
  before_id: number;
}

export interface ActivityPage {
  items: LedgerRow[];
  next: Cursor | null;
}

export interface ActivityFilters {
  q?: string;
  account_id?: number;
  category_id?: string;
  flow_type?: FlowType;
  date_from?: string;
  date_to?: string;
}

export interface FlowTotals {
  income: number;
  spending: number;
  net: number;
}

export interface TrendPeriod extends Period, FlowTotals {
  complete: boolean; // false for the period still running, which ends today
}

export interface Trend {
  granularity: Granularity;
  today: string;
  periods: TrendPeriod[];
}

export interface CategoryAmount {
  id: string;
  name: string;
  current: number; // spending for expense categories, income for income ones
  comparison: number;
}

export interface CategoryGroup extends CategoryAmount {
  children: CategoryAmount[]; // empty when the category has no subcategories
}

export interface Breakdown {
  granularity: Granularity;
  comparison: CompareMode;
  period: Period & { complete: boolean };
  comparison_periods: Period[];
  totals: { current: FlowTotals; comparison: FlowTotals };
  spending: CategoryGroup[];
  income: CategoryGroup[];
  featured: string[]; // the past year's biggest spending groups, in order: the donut gives them fixed colors
}

export interface RuleCondition {
  match_field: MatchField;
  pattern: string;
  direction: Direction | null; // null: money moving either way
}

export interface Rule extends RuleCondition {
  id: number;
  category_id: string;
  category_name: string;
  flow_type: FlowType;
  transaction_count: number;
  created_at: string;
  updated_at: string;
}

export interface RuleChanges {
  pattern?: string;
  direction?: Direction | null;
  category_id?: string;
}

export interface Category {
  id: string;
  parent_id: string | null;
  name: string;
  kind: FlowType;
  assignable: number;
}

export interface TransactionEdit {
  category_id?: string | null;
  note?: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("；") : null;
    throw new Error(message ?? `${response.status} ${response.statusText}`);
  }
  return body as T;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  status: () => request<Status>("/api/status"),
  overview: () => request<Overview>("/api/overview"),
  accounts: () => request<Account[]>("/api/accounts"),
  categories: () => request<Category[]>("/api/categories"),
  activity: (filters: ActivityFilters, cursor: Cursor | null, limit = 50) =>
    request<ActivityPage>(`/api/activity${query({ ...filters, ...cursor, limit })}`),
  editTransaction: (id: number, changes: TransactionEdit) => patch<LedgerRow>(`/api/transactions/${id}`, changes),
  rules: () => request<Rule[]>("/api/rules"),
  saveRule: (rule: RuleCondition & { category_id: string }) => post<Rule>("/api/rules", rule),
  editRule: (id: number, changes: RuleChanges) => patch<Rule>(`/api/rules/${id}`, changes),
  deleteRule: (id: number) => request<null>(`/api/rules/${id}`, { method: "DELETE" }),
  // A POST, so what the user types stays out of the server's access log.
  previewRule: (condition: RuleCondition) => post<{ matches: number }>("/api/rules/preview", condition),
  trend: (granularity: Granularity) => request<Trend>(`/api/insights/trend${query({ granularity })}`),
  breakdown: (granularity: Granularity, start: string | null, compare: CompareMode) =>
    request<Breakdown>(`/api/insights/breakdown${query({ granularity, start, compare })}`),
  startSync: () => post<{ started: boolean }>("/api/sync"),
  linkToken: (itemId?: number) => post<{ link_token: string }>("/api/link/token", { item_id: itemId ?? null }),
  exchange: (publicToken: string, institutionId: string | null, institutionName: string | null) =>
    post<{ item_id: number }>("/api/link/exchange", {
      public_token: publicToken,
      institution_id: institutionId,
      institution_name: institutionName,
    }),
  reconnected: (itemId: number) => post<{ item_id: number }>(`/api/items/${itemId}/reconnected`),
};
