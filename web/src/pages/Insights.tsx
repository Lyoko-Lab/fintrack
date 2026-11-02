import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Breakdown, type CategoryAmount, type CategoryGroup, type CompareMode, type Granularity } from "../api";
import { BarChart } from "../components/BarChart";
import { Donut, type Slice } from "../components/Donut";
import { Segmented } from "../components/Segmented";
import { StatTile } from "../components/StatTile";
import { axisLabel, compactMoney, compareLabel, money, percent, periodName, rangeLabel, shortDay } from "../format";
import { categoryName, useI18n, type Messages } from "../i18n";
import { navigate, replaceQuery } from "../router";

type Metric = "spending" | "income" | "net";
type View = "chart" | "table";

const GRANULARITIES: Granularity[] = ["day", "week", "month", "year"];
const METRICS: Metric[] = ["spending", "income", "net"];

/**
 * The view settings, as kept in the URL (only those that differ from the defaults), so the browser's
 * Back button returns to the same period, comparison and expanded rows after a drill-down.
 */
function settingsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const pick = <T extends string>(name: string, allowed: readonly T[], fallback: T): T => {
    const value = params.get(name);
    return allowed.find((option) => option === value) ?? fallback;
  };
  const granularity = pick<Granularity>("granularity", GRANULARITIES, "month");
  const compare = pick<CompareMode>("compare", ["previous", "year", "average"], "previous");
  const start = params.get("start");
  return {
    granularity,
    compare: granularity === "year" && compare === "year" ? "previous" : compare,
    metric: pick<Metric>("metric", METRICS, "spending"),
    view: pick<View>("view", ["chart", "table"], "chart"),
    focus: start && /^\d{4}-\d{2}-\d{2}$/.test(start) ? start : null,
    open: new Set((params.get("open") ?? "").split(",").filter(Boolean)) as ReadonlySet<string>,
  };
}

function compareOptions(t: Messages, granularity: Granularity): { value: CompareMode; label: string }[] {
  return [
    { value: "previous", label: t.insights.previous[granularity] },
    ...(granularity === "year" ? [] : [{ value: "year" as const, label: t.comparison.title(t.comparison.lastYear) }]),
    { value: "average", label: t.comparison.title(compareLabel("average", granularity, true)) },
  ];
}

/** "October 2026 (through Oct 28)", or just the name once the period is over. */
function focusTitle(t: Messages, breakdown: Breakdown): string {
  const { period, granularity } = breakdown;
  const running = !period.complete && (granularity === "month" || granularity === "year");
  return periodName(period, granularity) + (running ? t.insights.through(shortDay(period.end)) : "");
}

function Delta({ change, upIsGood }: { change: number; upIsGood: boolean }) {
  if (Math.abs(change) < 100) return <span className="delta neutral">—</span>;
  const up = change > 0;
  return (
    <span className={`delta ${up === upIsGood ? "good" : "bad"}`}>
      <span aria-hidden="true">{up ? "▲ " : "▼ "}</span>
      {money(change, { whole: true, signed: true })}
    </span>
  );
}

/** The current amount as a bar, with a mark where the comparison stood. */
function Meter({ value, mark, max }: { value: number; mark: number; max: number }) {
  return (
    <div className="meter" aria-hidden="true">
      {value > 0 && <div className="meter-fill" style={{ width: `${(value / max) * 100}%` }} />}
      {mark > 0 && <div className="meter-mark" style={{ left: `${(mark / max) * 100}%` }} />}
    </div>
  );
}

/** Which category groups moved spending the most, both ways: a small net change can hide big swings. */
function Drivers({ breakdown, label }: { breakdown: Breakdown; label: string }) {
  const { t } = useI18n();
  const change = breakdown.totals.current.spending - breakdown.totals.comparison.spending;
  const deltas = breakdown.spending
    .map((group) => ({ id: group.id, name: categoryName(group), delta: group.current - group.comparison }))
    .filter((group) => Math.abs(group.delta) >= 100);
  const top = (sign: 1 | -1) =>
    deltas
      .filter((group) => Math.sign(group.delta) === sign)
      .sort((a, b) => sign * (b.delta - a.delta))
      .slice(0, 3);
  const [ups, downs] = [top(1), top(-1)];
  const chips = (groups: typeof deltas) =>
    groups.map((group) => (
      <span key={group.id} className="chip">
        {group.name} {money(group.delta, { whole: true, signed: true })}
      </span>
    ));
  const amount = money(Math.abs(change), { whole: true });
  return (
    <p className="drivers">
      <span>
        {Math.abs(change) < 100
          ? t.insights.unchanged(label)
          : change > 0
            ? t.insights.higher(amount, label)
            : t.insights.lower(amount, label)}
      </span>
      {ups.length > 0 && <span>{t.insights.increases}</span>}
      {chips(ups)}
      {downs.length > 0 && <span>{t.insights.decreases}</span>}
      {chips(downs)}
    </p>
  );
}

const SLICE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
const REST = "__rest"; // not a category id: "other" already is one (Other spending)

/**
 * Where this period's spending went, as a donut: its five biggest groups by name, the rest as
 * one gray slice. A group that is usually among the biggest (data.featured) keeps its own color
 * in every period; a group that is big only now borrows a color left free. Slices go round in
 * color order, the order whose neighbouring pairs were checked for color-blind readers. Shares
 * are of the spending before refunds and reimbursements: a group that took in more than it
 * spent has no slice, and the note says so.
 */
function SpendingComposition({ data }: { data: Breakdown }) {
  const { t } = useI18n();
  const [active, setActive] = useState<string | null>(null);
  const spent = data.spending.filter((group) => group.current > 0);
  const gross = spent.reduce((sum, group) => sum + group.current, 0);
  if (gross === 0) return null;

  const named = [...spent].sort((a, b) => b.current - a.current).slice(0, SLICE_COLORS.length);
  const slotOf = new Map<string, number>();
  data.featured.forEach((id, slot) => named.some((group) => group.id === id) && slotOf.set(id, slot));
  const free = SLICE_COLORS.map((_, slot) => slot).filter((slot) => ![...slotOf.values()].includes(slot));
  for (const group of named) if (!slotOf.has(group.id)) slotOf.set(group.id, free.shift() ?? 0);

  const slices: (Slice & { members?: string[] })[] = named
    .map((group) => ({ key: group.id, label: categoryName(group), value: group.current, slot: slotOf.get(group.id) ?? 0 }))
    .sort((a, b) => a.slot - b.slot)
    .map(({ slot, ...slice }) => ({ ...slice, color: SLICE_COLORS[slot] }));
  const rest = spent.filter((group) => !named.includes(group));
  if (rest.length > 0) {
    slices.push({
      key: REST,
      label: t.insights.others(rest.length),
      value: rest.reduce((sum, group) => sum + group.current, 0),
      color: "var(--series-rest)",
      members: rest.map((group) => categoryName(group)),
    });
  }
  const offsets = data.spending.filter((group) => group.current < 0);

  return (
    <>
      <div className="composition">
        <Donut
          label={t.common.labelled(
            t.insights.byCategory.expense,
            t.common.list(slices.map((slice) => `${slice.label} ${percent(slice.value / gross)}`)),
          )}
          slices={slices}
          active={active}
          onActive={setActive}
          center={{ label: t.insights.totalSpending, value: money(data.totals.current.spending, { whole: true }) }}
          formatValue={(value) => money(value, { whole: true })}
        />
        <ul className="donut-legend">
          {slices.map((slice) => {
            const row = (
              <>
                <i className="swatch" style={{ background: slice.color }} />
                <span className="legend-name">
                  {slice.label}
                  {slice.members && <small>{t.common.list(slice.members)}</small>}
                </span>
                <span className="legend-share">{percent(slice.value / gross)}</span>
                <span className="legend-amount">{money(slice.value, { whole: true })}</span>
              </>
            );
            const highlight = {
              className: `legend-row${active === slice.key ? " active" : ""}`,
              onPointerEnter: () => setActive(slice.key),
              onPointerLeave: () => setActive(null),
            };
            return (
              <li key={slice.key}>
                {slice.key === REST ? (
                  <div {...highlight}>{row}</div>
                ) : (
                  <button
                    type="button"
                    {...highlight}
                    aria-label={t.insights.viewSlice(slice.label, percent(slice.value / gross), money(slice.value, { whole: true }))}
                    onFocus={() => setActive(slice.key)}
                    onBlur={() => setActive(null)}
                    onClick={() => navigate("activity", { category: slice.key, from: data.period.start, to: data.period.end })}
                  >
                    {row}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      {offsets.length > 0 && (
        <p className="donut-note">
          {t.insights.offsetsNote(
            money(gross, { whole: true }),
            offsets.map((group) => t.insights.offset(categoryName(group), money(group.current, { whole: true }))),
          )}
        </p>
      )}
    </>
  );
}

interface CategoryTableProps {
  kind: "expense" | "income";
  groups: CategoryGroup[];
  upIsGood: boolean;
  compareText: string; // the comparison, as a column heading
  period: { start: string; end: string };
  open: ReadonlySet<string>; // groups showing their subcategories
  onToggle(id: string): void;
  children?: ReactNode; // a chart above the table
}

function CategoryTable({ kind, groups, upIsGood, compareText, period, open, onToggle: toggle, children }: CategoryTableProps) {
  const { t } = useI18n();
  const max = Math.max(1, ...groups.flatMap((group) => [group.current, group.comparison]));
  // Shares are of everything that went out (or came in), before anything that offsets it.
  const gross = groups.reduce((sum, group) => sum + Math.max(group.current, 0), 0);

  const row = (entry: CategoryAmount, group: CategoryGroup | null) => {
    const name = categoryName(entry);
    return (
      <tr key={entry.id} className={group ? undefined : "child"}>
        <td>
          <div className="category-cell">
            {group &&
              (group.children.length > 0 ? (
                <button
                  type="button"
                  className="expander"
                  aria-expanded={open.has(group.id)}
                  aria-label={open.has(group.id) ? t.insights.collapse(name) : t.insights.expand(name)}
                  onClick={() => toggle(group.id)}
                >
                  {open.has(group.id) ? "▾" : "▸"}
                </button>
              ) : (
                <span className="expander" />
              ))}
            <button
              type="button"
              className="link-button"
              title={t.insights.viewTransactions}
              aria-label={t.insights.viewCategory(name)}
              onClick={() => navigate("activity", { category: entry.id, from: period.start, to: period.end })}
            >
              {name}
            </button>
          </div>
        </td>
        <td className="bar-cell">
          <Meter value={entry.current} mark={entry.comparison} max={max} />
        </td>
        <td className="num">{money(entry.current, { whole: true })}</td>
        <td className="num muted">{entry.current > 0 && gross > 0 ? percent(entry.current / gross) : "—"}</td>
        <td className="num muted">{money(entry.comparison, { whole: true })}</td>
        <td className="num">
          <Delta change={entry.current - entry.comparison} upIsGood={upIsGood} />
        </td>
      </tr>
    );
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{t.insights.byCategory[kind]}</h2>
        <div className="legend" aria-hidden="true">
          <span>
            <i className="legend-swatch" />
            {t.insights.thisPeriod}
          </span>
          <span>
            <i className="legend-mark" />
            {compareText}
          </span>
        </div>
      </div>
      {children}
      {groups.length === 0 ? (
        <p className="empty">{t.insights.none[kind]}</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table breakdown-table">
            <thead>
              <tr>
                <th>{t.insights.category}</th>
                <th className="bar-cell">
                  <span className="visually-hidden">{t.insights.comparisonChart}</span>
                </th>
                <th className="num">{t.insights.thisPeriod}</th>
                <th className="num">{t.insights.share}</th>
                <th className="num">{compareText}</th>
                <th className="num">{t.insights.change}</th>
              </tr>
            </thead>
            <tbody>
              {groups.flatMap((group) => [row(group, group), ...(open.has(group.id) ? group.children.map((child) => row(child, null)) : [])])}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function InsightsPage() {
  const { t } = useI18n();
  const [initial] = useState(settingsFromUrl);
  const [granularity, setGranularity] = useState<Granularity>(initial.granularity);
  const [compare, setCompare] = useState<CompareMode>(initial.compare);
  const [metric, setMetric] = useState<Metric>(initial.metric);
  const [focus, setFocus] = useState<string | null>(initial.focus); // start of the chosen period; null: the latest
  const [view, setView] = useState<View>(initial.view);
  const [open, setOpen] = useState(initial.open);
  const toggle = (id: string) =>
    setOpen((ids) => (ids.has(id) ? new Set([...ids].filter((other) => other !== id)) : new Set([...ids, id])));

  useEffect(() => {
    replaceQuery({
      granularity: granularity === "month" ? undefined : granularity,
      start: focus ?? undefined,
      compare: compare === "previous" ? undefined : compare,
      metric: metric === "spending" ? undefined : metric,
      view: view === "chart" ? undefined : view,
      open: [...open].join(","),
    });
  }, [granularity, focus, compare, metric, view, open]);

  const trend = useQuery({
    queryKey: ["insights", "trend", granularity],
    queryFn: () => api.trend(granularity),
    placeholderData: keepPreviousData,
  });
  const breakdown = useQuery({
    queryKey: ["insights", "breakdown", granularity, focus, compare],
    queryFn: () => api.breakdown(granularity, focus, compare),
    placeholderData: keepPreviousData,
  });

  const changeGranularity = (next: Granularity) => {
    setGranularity(next);
    setFocus(null);
    if (next === "year" && compare === "year") setCompare("previous");
  };

  // While another granularity loads, the previous data stays up, labelled by its own granularity.
  const shown = trend.data;
  const periods = shown?.periods ?? [];
  const selected = focus ?? periods.at(-1)?.start ?? null;
  const data = breakdown.data;
  const label = data ? compareLabel(data.comparison, data.granularity, data.period.complete) : "";
  const metricName = t.insights.metrics[metric];
  const chartTitle = shown ? t.insights.trend(metricName, shown.granularity) : metricName;

  return (
    <>
      <header className="page-header">
        <div>
          <h1>{t.insights.title}</h1>
          <p className="page-subtitle">{t.insights.subtitle}</p>
        </div>
      </header>

      <div className="toolbar">
        <Segmented
          label={t.insights.period}
          options={GRANULARITIES.map((value) => ({ value, label: t.insights.granularity[value] }))}
          value={granularity}
          onChange={changeGranularity}
        />
        <label className="toolbar-field">
          <span>{t.insights.compareWith}</span>
          <select value={compare} onChange={(event) => setCompare(event.target.value as CompareMode)}>
            {compareOptions(t, granularity).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {(trend.error ?? breakdown.error) && <p className="notice error">{(trend.error ?? breakdown.error)?.message}</p>}

      <section className={`panel${trend.isPlaceholderData ? " is-stale" : ""}`}>
        <div className="panel-header">
          <h2>{chartTitle}</h2>
          <div className="panel-tools">
            <Segmented<Metric>
              label={t.insights.metric}
              options={METRICS.map((value) => ({ value, label: t.insights.metrics[value] }))}
              value={metric}
              onChange={setMetric}
            />
            <button type="button" className="text-button" onClick={() => setView(view === "chart" ? "table" : "chart")}>
              {view === "chart" ? t.insights.showTable : t.insights.showChart}
            </button>
          </div>
        </div>
        {shown && periods.length > 0 ? (
          view === "chart" ? (
            <BarChart
              label={t.insights.chartLabel(chartTitle)}
              bars={periods.map((period) => ({
                key: period.start,
                label: axisLabel(period.start, shown.granularity),
                title: periodName(period, shown.granularity) + (period.complete ? "" : t.insights.inProgress),
                value: period[metric],
                partial: !period.complete,
              }))}
              selected={selected}
              onSelect={setFocus}
              formatValue={(value) => money(value, { whole: true })}
              formatTick={compactMoney}
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t.insights.periodColumn}</th>
                    <th className="num">{t.insights.metrics.income}</th>
                    <th className="num">{t.insights.metrics.spending}</th>
                    <th className="num">{t.insights.metrics.net}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...periods].reverse().map((period) => (
                    <tr key={period.start} className={period.start === selected ? "selected" : undefined}>
                      <td>
                        <button type="button" className="link-button" onClick={() => setFocus(period.start)}>
                          {periodName(period, shown.granularity)}
                          {period.complete ? "" : t.insights.inProgress}
                        </button>
                      </td>
                      <td className="num">{money(period.income, { whole: true })}</td>
                      <td className="num">{money(period.spending, { whole: true })}</td>
                      <td className="num">{money(period.net, { whole: true })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <p className="empty">{trend.isPending ? t.common.loading : t.common.noTransactions}</p>
        )}
        <p className="chart-caption">{view === "chart" ? t.insights.chartCaption : t.insights.tableCaption}</p>
      </section>

      {data && (
        <div className={breakdown.isPlaceholderData ? "is-stale" : undefined}>
          <div className="section-heading">
            <h2>{focusTitle(t, data)}</h2>
            <p className="muted">
              {t.insights.comparedWith(
                label,
                data.comparison_periods.map((period) => rangeLabel(period.start, period.end)),
                data.comparison === "average",
              )}
            </p>
          </div>
          <div className="kpi-row">
            <StatTile
              label={t.insights.metrics.income}
              value={data.totals.current.income}
              previous={data.totals.comparison.income}
              compareLabel={label}
              upIsGood
            />
            <StatTile
              label={t.insights.metrics.spending}
              value={data.totals.current.spending}
              previous={data.totals.comparison.spending}
              compareLabel={label}
              upIsGood={false}
            />
            <StatTile
              label={t.insights.metrics.net}
              value={data.totals.current.net}
              previous={data.totals.comparison.net}
              compareLabel={label}
              upIsGood
              footnote={t.insights.netFootnote}
            />
          </div>
          <Drivers breakdown={data} label={label} />
          <CategoryTable
            kind="expense"
            groups={data.spending}
            upIsGood={false}
            compareText={t.comparison.title(label)}
            period={data.period}
            open={open}
            onToggle={toggle}
          >
            <SpendingComposition data={data} />
          </CategoryTable>
          <CategoryTable
            kind="income"
            groups={data.income}
            upIsGood
            compareText={t.comparison.title(label)}
            period={data.period}
            open={open}
            onToggle={toggle}
          />
        </div>
      )}
    </>
  );
}
