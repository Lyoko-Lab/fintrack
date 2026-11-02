import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Account, type CardPayment, type Item, type ItemStatus, type Status } from "../api";
import { DueState } from "../components/DueState";
import { money, shortDay, whenLabel } from "../format";
import { useI18n } from "../i18n";
import { openPlaidLink } from "../plaidLink";
import { expectSync } from "../syncPolling";

const PLAID_TRIAL_ITEMS = 10;
const STATUS_ICON: Record<ItemStatus, string> = { active: "✓", login_required: "!", error: "×" };

export function AccountsPage({ status }: { status: Status | undefined }) {
  const { t } = useI18n();
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
    if (status?.env === "production" && !window.confirm(t.accounts.confirmConnect(PLAID_TRIAL_ITEMS, status.items.length))) {
      return;
    }
    setProblem(null);
    link.mutate(undefined);
  };

  const ready = Boolean(status?.plaid_configured);
  return (
    <>
      <header className="page-header">
        <div>
          <h1>{t.accounts.title}</h1>
          <p className="page-subtitle">
            {status?.syncing ? t.sync.running : t.sync.last(whenLabel(status?.last_success_at ?? null))} ·{" "}
            {t.accounts.schedule}
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
            {status?.syncing ? t.accounts.syncing : t.accounts.syncNow}
          </button>
          <button type="button" className="primary" disabled={!ready || link.isPending} onClick={connectNew}>
            {t.accounts.connect}
          </button>
        </div>
      </header>

      {status && !status.plaid_configured && (
        <div className="notice">
          {t.accounts.notConfigured}
          <code className="command">uv run fintrack secrets set PLAID_CLIENT_ID</code>
          <code className="command">uv run fintrack secrets set PLAID_SECRET_{status.env.toUpperCase()}</code>
        </div>
      )}
      {problem && <div className="notice error">{problem}</div>}

      {overview.data && status && status.items.length > 0 && (
        <div className="summary-row">
          <div>
            <span className="summary-label">{t.accounts.cash}</span>
            <span className="summary-value">{money(overview.data.net_cash.cash)}</span>
          </div>
          <div>
            <span className="summary-label">{t.accounts.cardBalances}</span>
            <span className="summary-value">{money(overview.data.net_cash.debt)}</span>
          </div>
          <div>
            <span className="summary-label">{t.accounts.netCash}</span>
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
        <p className="footnote">{t.accounts.trial(status.items.length, PLAID_TRIAL_ITEMS)}</p>
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
  const { t } = useI18n();
  const history = item.status === "active" ? t.accounts.history[item.transactions_status ?? ""] : undefined;
  const hasStatements = accounts.some((account) => payments.has(account.id));
  return (
    <section className="panel">
      <div className="panel-header">
        <div className="institution-title">
          <h2>{item.institution_name ?? t.accounts.unknownInstitution}</h2>
          <span className={`status ${item.status}`}>
            <span aria-hidden="true">{STATUS_ICON[item.status]}</span>
            {t.accounts.status[item.status]}
          </span>
        </div>
        <div className="institution-meta">
          {history && <span>{history}</span>}
          <span>{t.accounts.synced(whenLabel(item.last_synced_at))}</span>
          {item.status !== "active" && (
            <button type="button" disabled={busy} onClick={onReconnect}>
              {t.accounts.reconnect}
            </button>
          )}
        </div>
      </div>
      {item.last_error && <p className="error small">{item.last_error}</p>}
      <div className="table-scroll">
        <table className="accounts-table">
          <thead>
            <tr>
              <th>{t.accounts.account}</th>
              <th>{t.accounts.type}</th>
              <th className="num">{t.accounts.balance}</th>
              <th className="num">{t.accounts.available}</th>
              <th className="num">{t.accounts.limit}</th>
              {hasStatements && (
                <>
                  <th className="num">{t.accounts.statement}</th>
                  <th>{t.accounts.due}</th>
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
                  <td>{t.accounts.types[account.type] ?? account.type}</td>
                  <td className="num">{money(account.current_cents)}</td>
                  <td className="num">{money(account.available_cents)}</td>
                  <td className="num">{money(account.limit_cents)}</td>
                  {hasStatements && (
                    <>
                      <td className="num">
                        {payment ? (
                          <span className="cell-stack">
                            {money(payment.statement_cents)}
                            {payment.minimum_cents ? <small>{t.payments.minimumShort(money(payment.minimum_cents))}</small> : null}
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
                                ? t.payments.left(money(payment.remaining_cents))
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
