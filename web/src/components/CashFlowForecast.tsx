import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ForecastEvent } from "../api";
import { compactMoney, money, periodName, shortDay } from "../format";
import { useI18n } from "../i18n";
import { ForecastChart } from "./ForecastChart";
import { Segmented } from "./Segmented";

type View = "net" | "cash";
const VIEWS: View[] = ["cash", "net"];

/**
 * Where the cash in the bank, or net cash position, is headed over the next two months, after the
 * last two. The cash view comes first: it is the one card payments move, on the due dates of the
 * payment calendar. Net cash position (cash less what the cards owe) already counts a card's
 * balance when it is charged, so paying it changes nothing there.
 */
export function CashFlowForecast() {
  const { t } = useI18n();
  const query = useQuery({ queryKey: ["forecast"], queryFn: api.forecast });
  const [view, setView] = useState<View>("cash");
  const data = query.data;
  if (!data || data.history.length === 0 || data.forecast.length === 0) return null;

  const counts = (event: ForecastEvent) => (view === "net" ? event.kind !== "card" : event.account_type === "depository");
  const byDay = new Map<string, ForecastEvent[]>();
  for (const event of data.events.filter(counts)) byDay.set(event.date, [...(byDay.get(event.date) ?? []), event]);
  const past = data.history.map((point) => ({ date: point.date, value: point[view] }));
  const future = data.forecast.map((point) => ({ date: point.date, value: point[view] }));
  const now = past[past.length - 1];
  const end = future[future.length - 1];
  const lowest = future.reduce((min, point) => (point.value < min.value ? point : min));
  const change = end.value - now.value;
  const direction = Math.abs(change) < 100 ? "flat" : change > 0 ? "up" : "down";
  const whole = (cents: number) => money(cents, { whole: true });

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{t.forecast.title}</h2>
        <Segmented<View>
          label={t.forecast.view}
          options={VIEWS.map((value) => ({ value, label: t.forecast.views[value] }))}
          value={view}
          onChange={setView}
        />
      </div>

      <div className="forecast-summary">
        <div>
          <span className="summary-label">{t.forecast.today}</span>
          <span className="summary-value">{whole(now.value)}</span>
        </div>
        <div>
          <span className="summary-label">{t.forecast.projected(shortDay(end.date))}</span>
          <span className="summary-value projected">{whole(end.value)}</span>
          <span className={`stat-delta ${direction === "flat" ? "neutral" : direction === "up" ? "good" : "bad"}`}>
            <span aria-hidden="true">{direction === "up" ? "▲" : direction === "down" ? "▼" : "■"}</span>
            <span>
              {direction === "flat" ? t.stat.flat(t.forecast.vsToday) : t.stat[direction](whole(Math.abs(change)), t.forecast.vsToday)}
            </span>
          </span>
        </div>
        <div>
          <span className="summary-label">{t.forecast.lowest}</span>
          <span className="summary-value projected">{whole(lowest.value)}</span>
          <span className="muted small-text">{shortDay(lowest.date)}</span>
        </div>
      </div>

      <ForecastChart
        past={past}
        future={future}
        label={t.forecast.chartLabel(t.forecast.views[view], whole(now.value), whole(end.value), shortDay(end.date))}
        todayLabel={t.forecast.today}
        forecastLabel={t.forecast.forecastLabel}
        marked={new Set(byDay.keys())}
        formatValue={whole}
        formatTick={compactMoney}
        formatDate={(iso) => periodName({ start: iso, end: iso }, "day")}
        axisLabel={(iso) => {
          const [year, month, day] = iso.split("-").map(Number);
          return day === 1 ? t.dates.monthTick(month - 1, month === 1 ? year : undefined) : null;
        }}
        details={(iso) =>
          (byDay.get(iso) ?? []).map(
            (event) => `${event.kind === "card" ? t.forecast.cardPayment(event.name) : event.name} ${money(event.amount, { signed: true })}`,
          )
        }
      />
      <p className="chart-caption">{t.forecast.caption[view]}</p>

      <details className="forecast-details">
        <summary>{t.forecast.howEstimated}</summary>
        <ul>
          <li>{t.forecast.everyday(whole(data.daily_spending))}</li>
          {view === "cash" && <li>{t.forecast.cards}</li>}
          {view === "cash" && data.cards_without_due_date > 0 && <li>{t.forecast.noDueDate(data.cards_without_due_date)}</li>}
          <li>{t.forecast.oneOffs}</li>
        </ul>
        <h3>{t.forecast.recurring}</h3>
        {data.recurring.length === 0 ? (
          <p className="empty">{t.forecast.noRecurring}</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t.forecast.columns.name}</th>
                  <th>{t.forecast.columns.account}</th>
                  <th>{t.forecast.columns.every}</th>
                  <th className="num">{t.forecast.columns.amount}</th>
                  <th>{t.forecast.columns.next}</th>
                </tr>
              </thead>
              <tbody>
                {data.recurring.map((series) => (
                  <tr key={`${series.name}-${series.direction}-${series.account_name}`}>
                    <td className="wrap">{series.name}</td>
                    <td>{series.account_name}</td>
                    <td>{t.forecast.cadence[series.cadence]}</td>
                    <td className={`num${series.amount > 0 ? " inflow" : ""}`}>{money(series.amount, { signed: true })}</td>
                    <td>{shortDay(series.next_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
