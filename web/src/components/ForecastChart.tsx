import { useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export interface LinePoint {
  date: string;
  value: number;
}

interface ForecastChartProps {
  past: LinePoint[]; // through today: a solid line
  future: LinePoint[]; // after today: the forecast, a gray dashed line
  label: string; // accessible summary
  todayLabel: string;
  forecastLabel: string;
  marked: ReadonlySet<string>; // forecast days with something expected, marked with a dot
  formatValue(value: number): string;
  formatTick(value: number): string;
  formatDate(iso: string): string;
  axisLabel(iso: string): string | null; // the label under a day, if it gets one
  details(date: string): string[]; // more tooltip lines for a day, such as what is expected on it
}

const HEIGHT = 240;
const TOP = 24; // room for the Today and Forecast labels
const AXIS = 24;
const LEFT = 56;
const RIGHT = 12;

/** Round ticks covering [min, max]. A balance chart doesn't start at zero, unlike a bar chart. */
function ticksFor(min: number, max: number): number[] {
  if (max - min < 10_000) [min, max] = [min - 5_000, max + 5_000];
  const raw = (max - min) / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let tick = Math.floor(min / step) * step; tick < max + step; tick += step) ticks.push(Math.round(tick));
  return ticks;
}

/**
 * A balance over time that carries on as a forecast, like a stock chart: the past solid, the
 * forecast gray and dashed from today's point. Hover, or focus the chart and use the arrow
 * keys, to read any day's value and what is expected on it.
 */
export function ForecastChart(props: ForecastChartProps) {
  const { past, future, label, todayLabel, forecastLabel, marked, formatValue, formatTick, formatDate, axisLabel, details } = props;
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  const [keyboard, setKeyboard] = useState(false);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const points = [...past, ...future];
  const today = past.length - 1;
  const values = points.map((point) => point.value);
  const ticks = ticksFor(Math.min(...values), Math.max(...values));
  const [low, high] = [ticks[0], ticks[ticks.length - 1]];
  const bottom = HEIGHT - AXIS;
  const x = (index: number) => LEFT + (index / Math.max(points.length - 1, 1)) * (width - LEFT - RIGHT);
  const y = (value: number) => bottom - ((value - low) / (high - low)) * (bottom - TOP);
  const line = (from: number, to: number) =>
    points
      .slice(from, to + 1)
      .map((point, i) => `${i === 0 ? "M" : "L"}${x(from + i).toFixed(1)},${y(point.value).toFixed(1)}`)
      .join("");

  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const area = event.currentTarget.getBoundingClientRect();
    const index = Math.round(((event.clientX - area.left) / area.width) * (points.length - 1));
    setKeyboard(false);
    setActive(Math.min(Math.max(index, 0), points.length - 1));
  };
  const onKeyDown = (event: KeyboardEvent) => {
    const from = active ?? today;
    const target = { ArrowLeft: from - 1, ArrowRight: from + 1, Home: 0, End: points.length - 1 }[event.key];
    if (event.key === "Escape") setActive(null);
    if (target === undefined || target < 0 || target >= points.length) return;
    event.preventDefault();
    setKeyboard(true);
    setActive(target);
  };

  const shown = active === null ? null : points[active];
  const forecast = active !== null && active > today;
  const lines = shown ? [forecast ? `${forecastLabel} · ${formatDate(shown.date)}` : formatDate(shown.date), ...details(shown.date)] : [];
  const pointY = shown ? y(shown.value) : 0;
  return (
    <div className="chart forecast-chart" ref={box} style={{ height: HEIGHT }}>
      {width > 0 && points.length > 1 && (
        <svg
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onBlur={() => setActive(null)}
        >
          <g aria-hidden="true">
            {ticks.map((tick) => (
              <g key={tick}>
                <line className={tick === 0 ? "baseline" : "grid"} x1={LEFT} x2={width - RIGHT} y1={y(tick)} y2={y(tick)} />
                <text className="tick" x={LEFT - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {formatTick(tick)}
                </text>
              </g>
            ))}
            {points.map((point, index) => {
              const text = axisLabel(point.date);
              return (
                text && (
                  <text key={point.date} className="tick" x={x(index)} y={HEIGHT - 6} textAnchor="middle">
                    {text}
                  </text>
                )
              );
            })}
            <line className="today-line" x1={x(today)} x2={x(today)} y1={TOP} y2={bottom} />
            <text className="marker-label" x={x(today)} y={TOP - 10} textAnchor="middle">
              {todayLabel}
            </text>
            <text className="marker-label" x={width - RIGHT} y={TOP - 10} textAnchor="end">
              {forecastLabel}
            </text>
            <path className="line-past" d={line(0, today)} />
            <path className="line-forecast" d={line(today, points.length - 1)} />
            {points.map(
              (point, index) =>
                index > today &&
                marked.has(point.date) && <circle key={point.date} className="event-dot" cx={x(index)} cy={y(point.value)} r={3.5} />,
            )}
            {shown && active !== null && (
              <>
                <line className="crosshair" x1={x(active)} x2={x(active)} y1={TOP} y2={bottom} />
                <circle className={`active-dot${forecast ? " forecast" : ""}`} cx={x(active)} cy={pointY} r={5} />
              </>
            )}
          </g>
          <rect
            className="hover-area"
            x={LEFT}
            y={TOP}
            width={Math.max(width - LEFT - RIGHT, 0)}
            height={bottom - TOP}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
      )}
      {shown && active !== null && (
        <div
          className={`chart-tooltip${pointY < 96 ? " below" : ""}`}
          style={{ left: Math.min(Math.max(x(active), 90), width - 90), top: pointY < 96 ? pointY + 12 : pointY - 12 }}
        >
          <strong>{formatValue(shown.value)}</strong>
          {lines.map((text, i) => (
            <span key={i}>{text}</span>
          ))}
        </div>
      )}
      {/* What the arrow keys land on, read out by screen readers. */}
      <p className="visually-hidden" aria-live="polite">
        {keyboard && shown ? [formatValue(shown.value), ...lines].join(", ") : ""}
      </p>
    </div>
  );
}
