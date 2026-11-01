import { useQuery } from "@tanstack/react-query";
import { api, type CardPayment, type LedgerRow, type Status } from "../api";
import { DueState } from "../components/DueState";
import { StatTile } from "../components/StatTile";
import { TransactionList } from "../components/TransactionList";
import { money, periodLabel, shortDay } from "../format";
import { Link } from "../router";

function PaymentRow({ payment }: { payment: CardPayment }) {
  const [, month, day] = (payment.due_date ?? "").split("-").map(Number);
  return (
    <li className="payment-row">
      <div className="due-date" aria-hidden="true">
        {payment.due_date ? (
          <>
            <span className="due-month">{month}月</span>
            <span className="due-day">{day}</span>
          </>
        ) : (
          <span className="due-month">日期未知</span>
        )}
      </div>
      <div className="payment-main">
        {/* The card first: when the line is cut short on a phone, the bank's name is what goes. */}
        <span className="payment-card">
          {payment.account_name}
          {payment.account_mask ? ` ··${payment.account_mask}` : ""}
          {payment.institution_name ? <span className="muted"> · {payment.institution_name}</span> : null}
        </span>
        <span className="payment-meta">
          {payment.due_date && <span>{shortDay(payment.due_date)}到期</span>}
          <DueState payment={payment} />
          {payment.minimum_cents ? <span>最低还款 {money(payment.minimum_cents)}</span> : null}
        </span>
      </div>
      <div className="payment-amount">
        <strong>{money(payment.remaining_cents)}</strong>
        <span>
          {payment.paid_cents > 0 && payment.statement_cents !== null
            ? `账单 ${money(payment.statement_cents)}，已还 ${money(payment.paid_cents)}`
            : "本期应还"}
        </span>
      </div>
    </li>
  );
}

/** Credit card payments coming up, most urgent first; cards already paid are only counted. */
function UpcomingPayments() {
  const payments = useQuery({ queryKey: ["card-payments"], queryFn: api.cardPayments });
  const all = payments.data ?? [];
  if (all.length === 0) return null;
  const open = all.filter((payment) => payment.state !== "paid");
  const paid = all.length - open.length;
  const total = open.reduce((sum, payment) => sum + (payment.remaining_cents ?? 0), 0);
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>近期还款</h2>
        <Link to="accounts" className="panel-link">
          查看账户 →
        </Link>
      </div>
      {open.length > 0 ? (
        <ul className="payments">
          {open.map((payment) => (
            <PaymentRow key={payment.account_id} payment={payment} />
          ))}
        </ul>
      ) : (
        <p className="empty">本期的信用卡账单都已还清</p>
      )}
      <p className="payments-footnote">
        {[open.length > 0 && `待还合计 ${money(total)}`, paid > 0 && `另有 ${paid} 张卡本期已还清`].filter(Boolean).join("；")}
      </p>
    </section>
  );
}

export function OverviewPage({ status, onSelect }: { status: Status | undefined; onSelect(row: LedgerRow): void }) {
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const recent = useQuery({ queryKey: ["activity", "recent"], queryFn: () => api.activity({}, null, 12) });

  if (status && status.items.length === 0) {
    return (
      <>
        <header className="page-header">
          <h1>总览</h1>
        </header>
        <section className="panel empty-state">
          <h2>还没有连接银行</h2>
          <p>连接 Bank of America、Chase 和 American Express 之后，这里会显示本月收入、支出和净现金头寸。</p>
          <Link to="accounts" className="button primary">
            去连接银行
          </Link>
        </section>
      </>
    );
  }

  const data = overview.data;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>总览</h1>
          <p className="page-subtitle">
            {data
              ? `${periodLabel(data.period.start, data.period.end)}，对比上月同期 ${periodLabel(data.previous_period.start, data.previous_period.end)}`
              : " "}
          </p>
        </div>
      </header>

      {overview.error && <p className="notice error">{overview.error.message}</p>}
      <div className="kpi-row">
        {data ? (
          <>
            <StatTile
              label="本月收入"
              value={data.income.current}
              previous={data.income.previous}
              compareLabel="上月同期"
              upIsGood
            />
            <StatTile
              label="本月支出"
              value={data.spending.current}
              previous={data.spending.previous}
              compareLabel="上月同期"
              upIsGood={false}
            />
            <StatTile
              label="净现金头寸"
              value={data.net_cash.current}
              previous={data.net_cash.previous}
              compareLabel="上月同日"
              upIsGood
              footnote={`存款 ${money(data.net_cash.cash, { whole: true })} − 信用卡欠款 ${money(data.net_cash.debt, { whole: true })}`}
            />
          </>
        ) : (
          [0, 1, 2].map((i) => <div key={i} className="stat-tile skeleton" aria-hidden="true" />)
        )}
      </div>

      <UpcomingPayments />

      <section className="panel">
        <div className="panel-header">
          <h2>最近交易</h2>
          <Link to="activity" className="panel-link">
            查看全部 →
          </Link>
        </div>
        {recent.data && recent.data.items.length > 0 ? (
          <TransactionList rows={recent.data.items} onSelect={onSelect} />
        ) : (
          <p className="empty">{recent.isPending ? "加载中…" : "还没有交易"}</p>
        )}
      </section>
    </>
  );
}
