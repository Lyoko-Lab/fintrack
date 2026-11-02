import { useState } from "react";
import type { CardPayment } from "../api";
import { compactMoney, dayHeading, money, shortDay } from "../format";
import { useI18n } from "../i18n";
import { DueState } from "./DueState";

const MIN_WEEKS = 5;
const MAX_WEEKS = 7;
const LEVELS = 4; // shades of the one hue: the more owed that day, the bluer

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (day: Date) => `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
const addDays = (day: Date, days: number) => new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
const parseDay = (iso: string) => {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
};
const owed = (payments: CardPayment[]) =>
  payments.filter((p) => p.state !== "paid").reduce((sum, p) => sum + (p.remaining_cents ?? 0), 0);
// Tiles are small: whole dollars, then $1.7K from a thousand up. The list beside has the exact amounts.
const tileMoney = (cents: number) => (cents < 100_000 ? money(cents, { whole: true }) : compactMoney(cents));
const cardName = (p: CardPayment) => `${p.account_name}${p.account_mask ? ` ··${p.account_mask}` : ""}`;

/** One card's payment: which card, how it stands, what is left to pay. */
export function PaymentLine({ payment }: { payment: CardPayment }) {
  const { t } = useI18n();
  return (
    <li className="payment-row">
      <div className="payment-main">
        {/* The card first: when the line is cut short on a phone, the bank's name is what goes. */}
        <span className="payment-card">
          {cardName(payment)}
          {payment.institution_name ? <span className="muted"> · {payment.institution_name}</span> : null}
        </span>
        <span className="payment-meta">
          <DueState payment={payment} />
          {payment.minimum_cents ? <span>{t.payments.minimum(money(payment.minimum_cents))}</span> : null}
        </span>
      </div>
      <div className="payment-amount">
        <strong>{money(payment.remaining_cents)}</strong>
        <span>
          {payment.paid_cents > 0 && payment.statement_cents !== null
            ? t.payments.statementPaid(money(payment.statement_cents), money(payment.paid_cents))
            : t.payments.statementBalance}
        </span>
      </div>
    </li>
  );
}

function Legend() {
  const { t } = useI18n();
  return (
    <div className="cal-legend" aria-hidden="true">
      <span className="cal-ramp">
        {t.payments.less}
        {Array.from({ length: LEVELS }, (_, i) => (
          <i key={i} className={`heat-${i + 1}`} />
        ))}
        {t.payments.more}
      </span>
      <span>
        <i className="cal-swatch settled-swatch">✓</i>
        {t.payments.paid}
      </span>
      <span>
        <i className="cal-swatch today-swatch" />
        {t.payments.today}
      </span>
    </div>
  );
}

/**
 * The coming weeks as a mosaic of day tiles, from this week's Monday until the last due date
 * (five weeks at least). A day with payments due is shaded by how much is still owed on it,
 * and a click lists its cards beside the calendar (below it on a phone). Shading is one hue, so
 * it reads as "how much", while how a payment stands (overdue, paid) is spelled out in words.
 */
export function PaymentCalendar({ payments }: { payments: CardPayment[] }) {
  const { t } = useI18n();
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const todayIso = isoDay(today);
  const start = addDays(today, -((today.getDay() + 6) % 7));

  const byDay = new Map<string, CardPayment[]>();
  for (const payment of payments) {
    if (payment.due_date) byDay.set(payment.due_date, [...(byDay.get(payment.due_date) ?? []), payment]);
  }
  const lastDue = [...byDay.keys()].reduce((last, day) => (day > last ? day : last), todayIso);
  const daysShown = Math.round((parseDay(lastDue).getTime() - start.getTime()) / 86_400_000) + 1;
  const weeks = Math.min(MAX_WEEKS, Math.max(MIN_WEEKS, Math.ceil(daysShown / 7)));
  const most = Math.max(1, ...[...byDay.values()].map(owed));

  const firstOpen = payments.find((p) => p.state !== "paid" && p.due_date)?.due_date;
  const [selected, setSelected] = useState<string | null>(firstOpen ?? payments.find((p) => p.due_date)?.due_date ?? null);
  const chosen = selected ? (byDay.get(selected) ?? []) : [];
  const overdue = payments.filter((p) => p.state === "overdue");
  const undated = payments.filter((p) => !p.due_date && p.state !== "paid");

  const tile = (index: number) => {
    const day = addDays(start, index);
    const key = isoDay(day);
    const due = byDay.get(key);
    const amount = due ? owed(due) : 0;
    const level = amount > 0 ? Math.max(1, Math.ceil((amount / most) * LEVELS)) : 0;
    const settled = Boolean(due?.every((p) => p.state === "paid"));
    const className = [
      "cal-cell",
      key === todayIso && "today",
      key < todayIso && !amount && "past",
      level && `heat-${level}`,
      settled && "settled",
      key === selected && "selected",
    ]
      .filter(Boolean)
      .join(" ");
    // The month goes on its own small line, where the grid starts and where a month begins.
    const label = (
      <span className="cal-day">
        {(index === 0 || day.getDate() === 1) && <span className="cal-month">{t.dates.monthTick(day.getMonth())}</span>}
        {day.getDate()}
      </span>
    );
    if (!due) {
      return (
        <div key={key} className={className} aria-hidden="true">
          {label}
        </div>
      );
    }
    const summary = settled ? t.payments.allPaid : t.payments.toPay(money(amount));
    return (
      <button
        key={key}
        type="button"
        className={className}
        aria-pressed={key === selected}
        aria-label={t.payments.tile(shortDay(key), due.length, summary, due.some((p) => p.state === "overdue"))}
        onClick={() => setSelected(key)}
      >
        {label}
        <span className="cal-amount">{settled ? "✓" : tileMoney(amount)}</span>
        <span className="cal-count">{t.payments.cards(due.length)}</span>
      </button>
    );
  };

  return (
    <div className="payment-calendar">
      {overdue.length > 0 && (
        <p className="notice error">
          <span aria-hidden="true">! </span>
          {t.payments.overdueList(t.common.list(overdue.map((p) => `${cardName(p)} ${money(p.remaining_cents)}`)))}
        </p>
      )}

      <div className="payment-calendar-body">
        <div className="calendar-wrap">
          <div className="calendar" role="group" aria-label={t.payments.calendar}>
            {t.dates.weekdaysFromMonday.map((name, index) => (
              <span key={index} className="cal-weekday" aria-hidden="true">
                {name}
              </span>
            ))}
            {Array.from({ length: weeks * 7 }, (_, index) => tile(index))}
          </div>
          <Legend />
        </div>

        {selected && chosen.length > 0 && (
          <div className="cal-details">
            <h3>{t.payments.day(dayHeading(selected), chosen.length, owed(chosen) > 0 ? money(owed(chosen)) : null)}</h3>
            <ul className="payments">
              {chosen.map((payment) => (
                <PaymentLine key={payment.account_id} payment={payment} />
              ))}
            </ul>
          </div>
        )}
      </div>

      {undated.length > 0 && <p className="payments-footnote">{t.payments.undated(t.common.list(undated.map(cardName)))}</p>}
    </div>
  );
}
