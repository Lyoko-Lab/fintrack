import { percent } from "../format";

export interface Slice {
  key: string;
  label: string;
  value: number; // > 0
  color: string; // a CSS color, e.g. "var(--series-1)"
}

interface DonutProps {
  slices: Slice[]; // drawn clockwise from 12 o'clock
  active: string | null; // the slice to call out; the rest dim
  onActive(key: string | null): void;
  center: { label: string; value: string }; // shown in the hole while no slice is active
  formatValue(value: number): string;
  label: string; // accessible name; the legend beside it carries the numbers
}

const SIZE = 200;
const OUTER = 96;
const INNER = 62;

function point(angle: number, radius: number): string {
  return `${(SIZE / 2 + radius * Math.sin(angle)).toFixed(2)},${(SIZE / 2 - radius * Math.cos(angle)).toFixed(2)}`;
}

/** One slice of the ring, between two angles in radians measured clockwise from 12 o'clock. */
function ringPath(start: number, end: number): string {
  if (end - start >= 2 * Math.PI - 1e-9) {
    // An arc can't end where it starts, so a whole ring is drawn as two halves.
    return ringPath(start, start + Math.PI) + ringPath(start + Math.PI, end);
  }
  const large = end - start > Math.PI ? 1 : 0;
  return (
    `M${point(start, OUTER)}A${OUTER},${OUTER} 0 ${large} 1 ${point(end, OUTER)}` +
    `L${point(end, INNER)}A${INNER},${INNER} 0 ${large} 0 ${point(start, INNER)}Z`
  );
}

/** Part-to-whole at a glance: a ring of a few slices, with the total (or the hovered slice) in the hole. */
export function Donut({ slices, active, onActive, center, formatValue, label }: DonutProps) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const shown = slices.find((slice) => slice.key === active);
  let angle = 0;
  return (
    <div className="donut">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={label}>
        {slices.map((slice) => {
          const start = angle;
          angle += (slice.value / total) * 2 * Math.PI;
          return (
            <path
              key={slice.key}
              d={ringPath(start, angle)}
              fill={slice.color}
              className={active && active !== slice.key ? "dim" : undefined}
              onPointerEnter={() => onActive(slice.key)}
              onPointerLeave={() => onActive(null)}
            />
          );
        })}
      </svg>
      <div className="donut-center" aria-hidden="true">
        {shown ? (
          <>
            <span>{shown.label}</span>
            <strong>{percent(shown.value / total)}</strong>
            <span>{formatValue(shown.value)}</span>
          </>
        ) : (
          <>
            <span>{center.label}</span>
            <strong>{center.value}</strong>
          </>
        )}
      </div>
    </div>
  );
}
