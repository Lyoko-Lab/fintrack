import { useQuery } from "@tanstack/react-query";
import { api, type LedgerRow, type Status } from "../api";
import { PaymentCalendar } from "../components/PaymentCalendar";
import { StatTile } from "../components/StatTile";
import { TransactionList } from "../components/TransactionList";
import { money, periodLabel } from "../format";
import { useI18n } from "../i18n";
import { Link } from "../router";

/** Credit card payments coming up, as a calendar of the next few weeks, with what is left to pay. */
function UpcomingPayments() {
  const { t } = useI18n();
  const payments = useQuery({ queryKey: ["card-payments"], queryFn: api.cardPayments });
  const all = payments.data ?? [];
  if (all.length === 0) return null;
  const open = all.filter((payment) => payment.state !== "paid");
  const paid = all.length - open.length;
  const total = open.reduce((sum, payment) => sum + (payment.remaining_cents ?? 0), 0);
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{t.overview.payments}</h2>
        <span className="muted small-text">{t.overview.paymentsSummary(open.length > 0 ? money(total) : null, paid)}</span>
        <Link to="accounts" className="panel-link">
          {t.overview.viewAccounts}
        </Link>
      </div>
      <PaymentCalendar payments={all} />
    </section>
  );
}

export function OverviewPage({ status, onSelect }: { status: Status | undefined; onSelect(row: LedgerRow): void }) {
  const { t } = useI18n();
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const recent = useQuery({ queryKey: ["activity", "recent"], queryFn: () => api.activity({}, null, 12) });

  if (status && status.items.length === 0) {
    return (
      <>
        <header className="page-header">
          <h1>{t.overview.title}</h1>
        </header>
        <section className="panel empty-state">
          <h2>{t.overview.emptyTitle}</h2>
          <p>{t.overview.emptyText}</p>
          <Link to="accounts" className="button primary">
            {t.overview.emptyAction}
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
          <h1>{t.overview.title}</h1>
          <p className="page-subtitle">
            {data
              ? t.overview.period(
                  periodLabel(data.period.start, data.period.end),
                  periodLabel(data.previous_period.start, data.previous_period.end),
                )
              : " "}
          </p>
        </div>
      </header>

      {overview.error && <p className="notice error">{overview.error.message}</p>}
      <div className="kpi-row">
        {data ? (
          <>
            <StatTile
              label={t.overview.income}
              value={data.income.current}
              previous={data.income.previous}
              compareLabel={t.comparison.previousSoFar.month}
              upIsGood
            />
            <StatTile
              label={t.overview.spending}
              value={data.spending.current}
              previous={data.spending.previous}
              compareLabel={t.comparison.previousSoFar.month}
              upIsGood={false}
            />
            <StatTile
              label={t.overview.netCash}
              value={data.net_cash.current}
              previous={data.net_cash.previous}
              compareLabel={t.overview.sameDayLastMonth}
              upIsGood
              footnote={t.overview.netCashParts(
                money(data.net_cash.cash, { whole: true }),
                money(data.net_cash.debt, { whole: true }),
              )}
            />
          </>
        ) : (
          [0, 1, 2].map((i) => <div key={i} className="stat-tile skeleton" aria-hidden="true" />)
        )}
      </div>

      <UpcomingPayments />

      <section className="panel">
        <div className="panel-header">
          <h2>{t.overview.recent}</h2>
          <Link to="activity" className="panel-link">
            {t.overview.viewAll}
          </Link>
        </div>
        {recent.data && recent.data.items.length > 0 ? (
          <TransactionList rows={recent.data.items} onSelect={onSelect} />
        ) : (
          <p className="empty">{recent.isPending ? t.common.loading : t.common.noTransactions}</p>
        )}
      </section>
    </>
  );
}
