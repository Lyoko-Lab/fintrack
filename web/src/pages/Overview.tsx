import { useQuery } from "@tanstack/react-query";
import { api, type LedgerRow, type Status } from "../api";
import { PaymentCalendar } from "../components/PaymentCalendar";
import { StatTile } from "../components/StatTile";
import { TransactionList } from "../components/TransactionList";
import { money, periodLabel } from "../format";
import { Link } from "../router";

/** Credit card payments coming up, as a calendar of the next few weeks, with what is left to pay. */
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
        <span className="muted small-text">
          {[open.length > 0 ? `待还合计 ${money(total)}` : "本期账单都已还清", paid > 0 && open.length > 0 && `另有 ${paid} 张卡已还清`]
            .filter(Boolean)
            .join("，")}
        </span>
        <Link to="accounts" className="panel-link">
          查看账户 →
        </Link>
      </div>
      <PaymentCalendar payments={all} />
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
