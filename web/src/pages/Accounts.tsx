import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Account, type CardPayment, type Item, type ItemStatus, type Status } from "../api";
import { DueState } from "../components/DueState";
import { money, shortDay, whenLabel } from "../format";
import { openPlaidLink } from "../plaidLink";
import { expectSync } from "../syncPolling";

const PLAID_TRIAL_ITEMS = 10;
const ITEM_STATUS: Record<ItemStatus, [icon: string, label: string]> = {
  active: ["✓", "正常"],
  login_required: ["!", "需要重新登录"],
  error: ["×", "出错"],
};
const ACCOUNT_TYPE: Record<string, string> = { depository: "存款", credit: "信用卡", loan: "贷款", investment: "投资" };
const HISTORY: Record<string, string> = {
  NOT_READY: "Plaid 正在准备数据…",
  INITIAL_UPDATE_COMPLETE: "近 30 天已到，更早的历史还在拉取…",
};

export function AccountsPage({ status }: { status: Status | undefined }) {
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const cardPayments = useQuery({ queryKey: ["card-payments"], queryFn: api.cardPayments });
  const payments = new Map(cardPayments.data?.map((payment) => [payment.account_id, payment]));
  const [problem, setProblem] = useState<string | null>(null);

  const refreshStatus = () => {
    expectSync();
    void queryClient.invalidateQueries({ queryKey: ["status"] });
  };
  const sync = useMutation({ mutationFn: api.startSync, onSuccess: refreshStatus, onError: (e) => setProblem(e.message) });
  const link = useMutation({
    mutationFn: (itemId?: number) => openPlaidLink(itemId),
    onSuccess: (connected) => connected && refreshStatus(),
    onError: (e) => setProblem(e.message),
  });

  const connectNew = () => {
    if (
      status?.env === "production" &&
      !window.confirm(
        `每连接一家新银行会永久占用 1 个 Plaid Trial 额度（共 ${PLAID_TRIAL_ITEMS} 个，已用 ${status.items.length} 个）。\n` +
          "已经连过的银行掉线了，请用「重新登录」修复。\n\n确定要连接一家新的银行吗？",
      )
    )
      return;
    setProblem(null);
    link.mutate(undefined);
  };

  const ready = Boolean(status?.plaid_configured);
  return (
    <>
      <header className="page-header">
        <div>
          <h1>账户</h1>
          <p className="page-subtitle">
            {status?.syncing ? "正在同步…" : `上次同步：${whenLabel(status?.last_success_at ?? null)}`} · 每天 06:00 自动同步
          </p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            disabled={!ready || !status?.items.length || status.syncing || sync.isPending}
            onClick={() => {
              setProblem(null);
              sync.mutate();
            }}
          >
            {status?.syncing ? "同步中…" : "立即同步"}
          </button>
          <button type="button" className="primary" disabled={!ready || link.isPending} onClick={connectNew}>
            连接新银行
          </button>
        </div>
      </header>

      {status && !status.plaid_configured && (
        <div className="notice">
          还没有配置 Plaid 密钥。在终端运行 <code>uv run fintrack secrets set PLAID_CLIENT_ID</code> 和{" "}
          <code>uv run fintrack secrets set PLAID_SECRET_{status.env.toUpperCase()}</code>，然后刷新本页。
        </div>
      )}
      {problem && <div className="notice error">{problem}</div>}

      {overview.data && status && status.items.length > 0 && (
        <div className="summary-row">
          <div>
            <span className="summary-label">存款合计</span>
            <span className="summary-value">{money(overview.data.net_cash.cash)}</span>
          </div>
          <div>
            <span className="summary-label">信用卡欠款</span>
            <span className="summary-value">{money(overview.data.net_cash.debt)}</span>
          </div>
          <div>
            <span className="summary-label">净现金头寸</span>
            <span className="summary-value">{money(overview.data.net_cash.current)}</span>
          </div>
        </div>
      )}

      {status?.items.map((item) => (
        <Institution
          key={item.id}
          item={item}
          accounts={accounts.data?.filter((a) => a.item_id === item.id) ?? []}
          payments={payments}
          onReconnect={() => {
            setProblem(null);
            link.mutate(item.id);
          }}
          busy={link.isPending}
        />
      ))}

      {status?.env === "production" && (
        <p className="footnote">
          Plaid Trial 额度：已用 {status.items.length} / {PLAID_TRIAL_ITEMS}。额度删除后不返还，连接掉线请用「重新登录」。
        </p>
      )}
    </>
  );
}

function Institution({
  item,
  accounts,
  payments,
  onReconnect,
  busy,
}: {
  item: Item;
  accounts: Account[];
  payments: Map<number, CardPayment>; // by account id, for credit cards with a statement
  onReconnect(): void;
  busy: boolean;
}) {
  const [icon, label] = ITEM_STATUS[item.status];
  const history = item.status === "active" ? HISTORY[item.transactions_status ?? ""] : undefined;
  const hasStatements = accounts.some((account) => payments.has(account.id));
  return (
    <section className="panel">
      <div className="panel-header">
        <div className="institution-title">
          <h2>{item.institution_name ?? "未知机构"}</h2>
          <span className={`status ${item.status}`}>
            <span aria-hidden="true">{icon}</span>
            {label}
          </span>
        </div>
        <div className="institution-meta">
          {history && <span>{history}</span>}
          <span>同步于 {whenLabel(item.last_synced_at)}</span>
          {item.status !== "active" && (
            <button type="button" disabled={busy} onClick={onReconnect}>
              重新登录
            </button>
          )}
        </div>
      </div>
      {item.last_error && <p className="error small">{item.last_error}</p>}
      <div className="table-scroll">
        <table className="accounts-table">
          <thead>
            <tr>
              <th>账户</th>
              <th>类型</th>
              <th className="num">余额 / 欠款</th>
              <th className="num">可用</th>
              <th className="num">信用额度</th>
              {hasStatements && (
                <>
                  <th className="num">本期账单</th>
                  <th>还款日</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const payment = payments.get(account.id);
              return (
                <tr key={account.id}>
                  <td>
                    {account.name} {account.mask && <span className="muted">··{account.mask}</span>}
                  </td>
                  <td>{ACCOUNT_TYPE[account.type] ?? account.type}</td>
                  <td className="num">{money(account.current_cents)}</td>
                  <td className="num">{money(account.available_cents)}</td>
                  <td className="num">{money(account.limit_cents)}</td>
                  {hasStatements && (
                    <>
                      <td className="num">
                        {payment ? (
                          <span className="cell-stack">
                            {money(payment.statement_cents)}
                            {payment.minimum_cents ? <small>最低 {money(payment.minimum_cents)}</small> : null}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {payment ? (
                          <span className="cell-stack">
                            {payment.due_date ? shortDay(payment.due_date) : "—"}
                            <small>
                              <DueState payment={payment} />
                              {payment.state === "due" && payment.paid_cents > 0 && payment.remaining_cents !== null
                                ? `，还差 ${money(payment.remaining_cents)}`
                                : null}
                            </small>
                          </span>
                        ) : null}
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
