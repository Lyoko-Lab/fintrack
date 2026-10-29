import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Breakdown, type CategoryAmount, type CategoryGroup, type CompareMode, type Granularity } from "../api";
import { BarChart } from "../components/BarChart";
import { Donut, type Slice } from "../components/Donut";
import { Segmented } from "../components/Segmented";
import { StatTile } from "../components/StatTile";
import { axisLabel, compactMoney, compareLabel, everyLabel, money, percent, periodName, rangeLabel, shortDay } from "../format";
import { navigate, replaceQuery } from "../router";

type Metric = "spending" | "income" | "net";
type View = "chart" | "table";

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "day", label: "日" },
  { value: "week", label: "周" },
  { value: "month", label: "月" },
  { value: "year", label: "年" },
];
const METRICS: { value: Metric; label: string }[] = [
  { value: "spending", label: "支出" },
  { value: "income", label: "收入" },
  { value: "net", label: "结余" },
];
const PREVIOUS: Record<Granularity, string> = { day: "前一天", week: "上一周", month: "上个月", year: "上一年" };

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
  const granularity = pick<Granularity>("granularity", ["day", "week", "month", "year"], "month");
  const compare = pick<CompareMode>("compare", ["previous", "year", "average"], "previous");
  const start = params.get("start");
  return {
    granularity,
    compare: granularity === "year" && compare === "year" ? "previous" : compare,
    metric: pick<Metric>("metric", ["spending", "income", "net"], "spending"),
    view: pick<View>("view", ["chart", "table"], "chart"),
    focus: start && /^\d{4}-\d{2}-\d{2}$/.test(start) ? start : null,
    open: new Set((params.get("open") ?? "").split(",").filter(Boolean)) as ReadonlySet<string>,
  };
}

function compareOptions(granularity: Granularity): { value: CompareMode; label: string }[] {
  return [
    { value: "previous", label: PREVIOUS[granularity] },
    ...(granularity === "year" ? [] : [{ value: "year" as const, label: "去年同期" }]),
    { value: "average", label: compareLabel("average", granularity, true) },
  ];
}

/** "2026年10月（截至10月28日）", or just the name once the period is over. */
function focusTitle(breakdown: Breakdown): string {
  const { period, granularity } = breakdown;
  const running = !period.complete && (granularity === "month" || granularity === "year");
  return periodName(period, granularity) + (running ? `（截至${shortDay(period.end)}）` : "");
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
  const change = breakdown.totals.current.spending - breakdown.totals.comparison.spending;
  const deltas = breakdown.spending
    .map((group) => ({ id: group.id, name: group.name, delta: group.current - group.comparison }))
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
  return (
    <p className="drivers">
      <span>
        {Math.abs(change) < 100
          ? `支出和${label}基本持平。`
          : `支出比${label}${change > 0 ? "多" : "少"} ${money(Math.abs(change), { whole: true })}。`}
      </span>
      {ups.length > 0 && <span>增加最多：</span>}
      {chips(ups)}
      {downs.length > 0 && <span>减少最多：</span>}
      {chips(downs)}
    </p>
  );
}

const SLICE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
const REST = "__rest"; // not a category id: "other" already is one (其他支出)

/**
 * Where this period's spending went, as a donut: its five biggest groups by name, the rest as
 * one gray slice. A group that is usually among the biggest (data.featured) keeps its own color
 * in every period; a group that is big only now borrows a color left free. Slices go round in
 * color order, the order whose neighbouring pairs were checked for color-blind readers. Shares
 * are of the spending before refunds and reimbursements: a group that took in more than it
 * spent has no slice, and the note says so.
 */
function SpendingComposition({ data }: { data: Breakdown }) {
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
    .map((group) => ({ key: group.id, label: group.name, value: group.current, slot: slotOf.get(group.id) ?? 0 }))
    .sort((a, b) => a.slot - b.slot)
    .map(({ slot, ...slice }) => ({ ...slice, color: SLICE_COLORS[slot] }));
  const rest = spent.filter((group) => !named.includes(group));
  if (rest.length > 0) {
    slices.push({
      key: REST,
      label: `其余 ${rest.length} 类`,
      value: rest.reduce((sum, group) => sum + group.current, 0),
      color: "var(--series-rest)",
      members: rest.map((group) => group.name),
    });
  }
  const offsets = data.spending.filter((group) => group.current < 0);

  return (
    <>
      <div className="composition">
        <Donut
          label={`支出构成：${slices.map((slice) => `${slice.label} ${percent(slice.value / gross)}`).join("，")}`}
          slices={slices}
          active={active}
          onActive={setActive}
          center={{ label: "本期支出", value: money(data.totals.current.spending, { whole: true }) }}
          formatValue={(value) => money(value, { whole: true })}
        />
        <ul className="donut-legend">
          {slices.map((slice) => {
            const row = (
              <>
                <i className="swatch" style={{ background: slice.color }} />
                <span className="legend-name">
                  {slice.label}
                  {slice.members && <small>{slice.members.join("、")}</small>}
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
                    aria-label={`${slice.label} ${percent(slice.value / gross)}，${money(slice.value, { whole: true })}：在交易流里查看`}
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
          比例按退款和报销抵扣前的 {money(gross, { whole: true })} 计算。
          {offsets.map((group) => `${group.name}（净额 ${money(group.current, { whole: true })}）`).join("、")}
          这一期收回的钱比花出去的多，不在图中。
        </p>
      )}
    </>
  );
}

interface CategoryTableProps {
  noun: "支出" | "收入";
  groups: CategoryGroup[];
  upIsGood: boolean;
  compareText: string;
  period: { start: string; end: string };
  open: ReadonlySet<string>; // groups showing their subcategories
  onToggle(id: string): void;
  children?: ReactNode; // a chart above the table
}

function CategoryTable({ noun, groups, upIsGood, compareText, period, open, onToggle: toggle, children }: CategoryTableProps) {
  const max = Math.max(1, ...groups.flatMap((group) => [group.current, group.comparison]));
  // Shares are of everything that went out (or came in), before anything that offsets it.
  const gross = groups.reduce((sum, group) => sum + Math.max(group.current, 0), 0);

  const row = (entry: CategoryAmount, group: CategoryGroup | null) => (
    <tr key={entry.id} className={group ? undefined : "child"}>
      <td>
        <div className="category-cell">
          {group &&
            (group.children.length > 0 ? (
              <button
                type="button"
                className="expander"
                aria-expanded={open.has(group.id)}
                aria-label={`${open.has(group.id) ? "收起" : "展开"}${group.name}`}
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
            title="在交易流里查看这些交易"
            aria-label={`${entry.name}：在交易流里查看这些交易`}
            onClick={() => navigate("activity", { category: entry.id, from: period.start, to: period.end })}
          >
            {entry.name}
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

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{noun}构成</h2>
        <div className="legend" aria-hidden="true">
          <span>
            <i className="legend-swatch" />
            本期
          </span>
          <span>
            <i className="legend-mark" />
            {compareText}
          </span>
        </div>
      </div>
      {children}
      {groups.length === 0 ? (
        <p className="empty">这一期没有{noun}</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table breakdown-table">
            <thead>
              <tr>
                <th>分类</th>
                <th className="bar-cell">
                  <span className="visually-hidden">对比图</span>
                </th>
                <th className="num">本期</th>
                <th className="num">占比</th>
                <th className="num">{compareText}</th>
                <th className="num">变化</th>
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
  const metricName = METRICS.find((m) => m.value === metric)?.label ?? "";

  return (
    <>
      <header className="page-header">
        <div>
          <h1>分析</h1>
          <p className="page-subtitle">收入和支出怎么变化，钱花在了哪里。转账不计入。</p>
        </div>
      </header>

      <div className="toolbar">
        <Segmented label="时间粒度" options={GRANULARITIES} value={granularity} onChange={changeGranularity} />
        <label className="toolbar-field">
          <span>对比</span>
          <select value={compare} onChange={(event) => setCompare(event.target.value as CompareMode)}>
            {compareOptions(granularity).map((option) => (
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
          <h2>
            {shown ? everyLabel(shown.granularity) : ""}
            {metricName}
          </h2>
          <div className="panel-tools">
            <Segmented<Metric> label="指标" options={METRICS} value={metric} onChange={setMetric} />
            <button type="button" className="text-button" onClick={() => setView(view === "chart" ? "table" : "chart")}>
              {view === "chart" ? "显示表格" : "显示图表"}
            </button>
          </div>
        </div>
        {shown && periods.length > 0 ? (
          view === "chart" ? (
            <BarChart
              label={`${everyLabel(shown.granularity)}${metricName}，选择一期查看明细`}
              bars={periods.map((period) => ({
                key: period.start,
                label: axisLabel(period.start, shown.granularity),
                title: periodName(period, shown.granularity) + (period.complete ? "" : "（进行中）"),
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
                    <th>周期</th>
                    <th className="num">收入</th>
                    <th className="num">支出</th>
                    <th className="num">结余</th>
                  </tr>
                </thead>
                <tbody>
                  {[...periods].reverse().map((period) => (
                    <tr key={period.start} className={period.start === selected ? "selected" : undefined}>
                      <td>
                        <button type="button" className="link-button" onClick={() => setFocus(period.start)}>
                          {periodName(period, shown.granularity)}
                          {period.complete ? "" : "（进行中）"}
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
          <p className="empty">{trend.isPending ? "加载中…" : "还没有交易"}</p>
        )}
        <p className="chart-caption">
          {view === "chart" ? "点一根柱子，下面就换成那一期的明细。颜色较浅的柱子是还没结束的这一期。" : "点周期名称，下面就换成那一期的明细。"}
        </p>
      </section>

      {data && (
        <div className={breakdown.isPlaceholderData ? "is-stale" : undefined}>
          <div className="section-heading">
            <h2>{focusTitle(data)}</h2>
            <p className="muted">
              对比{label}：{data.comparison_periods.map((period) => rangeLabel(period.start, period.end)).join("、")}
              {data.comparison === "average" ? " 的平均值" : ""}
            </p>
          </div>
          <div className="kpi-row">
            <StatTile label="收入" value={data.totals.current.income} previous={data.totals.comparison.income} compareLabel={label} upIsGood />
            <StatTile
              label="支出"
              value={data.totals.current.spending}
              previous={data.totals.comparison.spending}
              compareLabel={label}
              upIsGood={false}
            />
            <StatTile
              label="结余"
              value={data.totals.current.net}
              previous={data.totals.comparison.net}
              compareLabel={label}
              upIsGood
              footnote="收入减去支出"
            />
          </div>
          <Drivers breakdown={data} label={label} />
          <CategoryTable
            noun="支出"
            groups={data.spending}
            upIsGood={false}
            compareText={label}
            period={data.period}
            open={open}
            onToggle={toggle}
          >
            <SpendingComposition data={data} />
          </CategoryTable>
          <CategoryTable
            noun="收入"
            groups={data.income}
            upIsGood
            compareText={label}
            period={data.period}
            open={open}
            onToggle={toggle}
          />
        </div>
      )}
    </>
  );
}
