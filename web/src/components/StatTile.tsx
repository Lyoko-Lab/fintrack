import type { ReactNode } from "react";
import { money, percent } from "../format";

interface StatTileProps {
  label: string;
  value: number; // cents
  previous: number | null; // cents at the comparison point
  compareLabel: string; // e.g. "上月同期"
  upIsGood: boolean;
  footnote?: ReactNode;
}

/** A headline number with its change against a named earlier point. Direction is spelled out, never color alone. */
export function StatTile({ label, value, previous, compareLabel, upIsGood, footnote }: StatTileProps) {
  const change = previous === null ? null : value - previous;
  // Values are shown in whole dollars, so a change under $1 reads as no change.
  const direction = change === null || Math.abs(change) < 100 ? "flat" : change > 0 ? "up" : "down";
  const tone = direction === "flat" ? "neutral" : (direction === "up") === upIsGood ? "good" : "bad";

  return (
    <section className="stat-tile" aria-label={label}>
      <h2 className="stat-label">{label}</h2>
      <p className="stat-value" title={money(value)}>
        {money(value, { whole: true })}
      </p>
      {change !== null && (
        <p className={`stat-delta ${tone}`}>
          <span aria-hidden="true">{direction === "up" ? "▲" : direction === "down" ? "▼" : "■"}</span>
          {direction === "flat" ? (
            <span>与{compareLabel}持平</span>
          ) : (
            <span>
              {/* A percentage of zero or of a negative position (net cash can be below zero) says nothing. */}
              {previous !== null && previous > 0 ? `${percent(change / previous)} · ` : ""}比{compareLabel}
              {direction === "up" ? "多" : "少"} {money(Math.abs(change), { whole: true })}
            </span>
          )}
        </p>
      )}
      {footnote && <p className="stat-footnote">{footnote}</p>}
    </section>
  );
}
