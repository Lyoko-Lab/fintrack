import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

export interface Bar {
  key: string;
  label: string; // under the bar
  title: string; // in the tooltip and for screen readers
  value: number;
  partial?: boolean; // a period still running, drawn lighter
}

interface BarChartProps {
  bars: Bar[];
  selected: string | null;
  onSelect(key: string): void;
  formatValue(value: number): string;
  formatTick(value: number): string;
  label: string; // accessible name
}

const HEIGHT = 236;
const TOP = 12;
const AXIS = 24; // room for the labels under the bars
const LEFT = 52; // room for the value ticks
const RIGHT = 4;
const MAX_BAR = 24;
const LABEL_WIDTH = 46;

/** Round tick values covering [min, max], always including zero. */
function ticksFor(min: number, max: number): number[] {
  if (min === max) return [0, 10_000];
  const raw = (max - min) / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let tick = Math.floor(min / step) * step; tick < max + step; tick += step) ticks.push(Math.round(tick));
  return ticks;
}

/** A bar from the baseline to its value, rounded only at the value end. */
function barPath(x: number, width: number, base: number, end: number): string {
  const height = Math.abs(end - base);
  if (height < 0.5) return "";
  const r = Math.min(4, width / 2, height);
  const corner = end < base ? end + r : end - r;
  return `M${x},${base}V${corner}Q${x},${end} ${x + r},${end}H${x + width - r}Q${x + width},${end} ${x + width},${corner}V${base}Z`;
}

/**
 * A column chart that doubles as a period picker: click a bar, or focus the chart and use the
 * arrow keys, to select it. Every bar shows its value in a tooltip on hover and on focus.
 */
export function BarChart({ bars, selected, onSelect, formatValue, formatTick, label }: BarChartProps) {
  const box = useRef<HTMLDivElement>(null);
  const hits = useRef<(SVGRectElement | null)[]>([]);
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<number | null>(null); // hovered or focused
  const [focused, setFocused] = useState<number | null>(null);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const values = bars.map((bar) => bar.value);
  const ticks = ticksFor(Math.min(0, ...values), Math.max(0, ...values));
  const [low, high] = [ticks[0], ticks[ticks.length - 1]];
  const bottom = HEIGHT - AXIS;
  const y = (value: number) => bottom - ((value - low) / (high - low)) * (bottom - TOP);
  const band = bars.length ? (width - LEFT - RIGHT) / bars.length : 0;
  const barWidth = Math.max(1, Math.min(MAX_BAR, band - 2)); // at least a 2px gap between neighbours
  const labelEvery = Math.max(1, Math.ceil(LABEL_WIDTH / band));
  const x = (index: number) => LEFT + index * band;
  const selectedIndex = bars.findIndex((bar) => bar.key === selected);
  const tabStop = selectedIndex >= 0 ? selectedIndex : bars.length - 1;

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const target = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: bars.length - 1 }[event.key];
    if (target === undefined || target < 0 || target >= bars.length) return;
    event.preventDefault();
    onSelect(bars[target].key);
    hits.current[target]?.focus();
  };

  const tip = active === null ? null : bars[active];
  return (
    // Full height before the width is measured, so the page doesn't change length on first render.
    <div className="chart" ref={box} style={{ height: HEIGHT }}>
      {width > 0 && (
        <svg width={width} height={HEIGHT}>
          <g aria-hidden="true">
            {ticks.map((tick) => (
              <g key={tick}>
                <line className={tick === 0 ? "baseline" : "grid"} x1={LEFT} x2={width - RIGHT} y1={y(tick)} y2={y(tick)} />
                <text className="tick" x={LEFT - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {formatTick(tick)}
                </text>
              </g>
            ))}
            {selectedIndex >= 0 && <rect className="band" x={x(selectedIndex)} y={TOP} width={band} height={bottom - TOP} rx={4} />}
            {bars.map((bar, index) => (
              <path
                key={bar.key}
                className={`bar${bar.value < 0 ? " negative" : ""}${bar.partial ? " partial" : ""}`}
                d={barPath(x(index) + (band - barWidth) / 2, barWidth, y(0), y(bar.value))}
              />
            ))}
            {bars.map(
              (bar, index) =>
                // Thin the labels out when they would collide, always keeping the latest one.
                index % labelEvery === (bars.length - 1) % labelEvery && (
                  <text
                    key={bar.key}
                    className={`tick${index === selectedIndex ? " current" : ""}`}
                    x={x(index) + band / 2}
                    y={HEIGHT - 6}
                    textAnchor="middle"
                  >
                    {bar.label}
                  </text>
                ),
            )}
          </g>
          <g role="radiogroup" aria-label={label}>
            {bars.map((bar, index) => (
              <rect
                key={bar.key}
                ref={(element) => {
                  hits.current[index] = element;
                }}
                className="hit"
                x={x(index)}
                y={TOP}
                width={band}
                height={bottom - TOP}
                role="radio"
                aria-checked={index === selectedIndex}
                aria-label={`${bar.title}：${formatValue(bar.value)}`}
                tabIndex={index === tabStop ? 0 : -1}
                onClick={() => onSelect(bar.key)}
                onKeyDown={(event) => onKeyDown(event, index)}
                onPointerEnter={() => setActive(index)}
                onPointerLeave={() => setActive(null)}
                onFocus={(event) => {
                  setActive(index);
                  // Ring only for keyboard focus, as :focus-visible would; a click already shows the selection.
                  if (event.currentTarget.matches(":focus-visible")) setFocused(index);
                }}
                onBlur={() => {
                  setActive(null);
                  setFocused(null);
                }}
              />
            ))}
          </g>
          {focused !== null && (
            <rect className="focus-ring" x={x(focused) + 1} y={TOP + 1} width={band - 2} height={bottom - TOP - 2} rx={4} />
          )}
        </svg>
      )}
      {tip && active !== null && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(Math.max(x(active) + band / 2, 70), width - 70),
            top: Math.min(y(tip.value), y(0)) - 8,
          }}
        >
          <strong>{formatValue(tip.value)}</strong>
          <span>{tip.title}</span>
        </div>
      )}
    </div>
  );
}
