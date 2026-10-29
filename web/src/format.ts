import type { CompareMode, Granularity } from "./api";

const MINUS = "−";
const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const wholeDollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const compactDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});
const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** $1,234.56 from cents. `whole` drops the cents; `signed` adds + to positive amounts. */
export function money(cents: number | null | undefined, { whole = false, signed = false } = {}): string {
  if (cents == null) return "—";
  const text = (whole ? wholeDollars : dollars).format(Math.abs(cents) / 100);
  if (cents < 0) return MINUS + text;
  return signed && cents > 0 ? `+${text}` : text;
}

/** Axis ticks: $0, $500, $1.5K, $12K. */
export function compactMoney(cents: number): string {
  const text = compactDollars.format(Math.abs(cents) / 100);
  return cents < 0 ? MINUS + text : text;
}

/** A calendar date ("2026-10-28") as a local Date at midnight, so it never shifts by a time zone. */
function parseDay(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function daysAgo(day: Date, now = new Date()): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today.getTime() - day.getTime()) / 86_400_000);
}

export function shortDay(iso: string): string {
  const day = parseDay(iso);
  return `${day.getMonth() + 1}月${day.getDate()}日`;
}

/** Feed section heading: "今天 · 10月28日 周二". */
export function dayHeading(iso: string): string {
  const day = parseDay(iso);
  const label = `${shortDay(iso)} ${WEEKDAYS[day.getDay()]}`;
  const ago = daysAgo(day);
  if (ago === 0) return `今天 · ${label}`;
  if (ago === 1) return `昨天 · ${label}`;
  return day.getFullYear() === new Date().getFullYear() ? label : `${day.getFullYear()}年${label}`;
}

/** "10月1日–28日", or "9月29日–10月3日" across months. */
export function periodLabel(start: string, end: string): string {
  const [from, to] = [parseDay(start), parseDay(end)];
  return from.getMonth() === to.getMonth() ? `${shortDay(start)}–${to.getDate()}日` : `${shortDay(start)}–${shortDay(end)}`;
}

/** Like periodLabel, but names the year when it isn't this one: "2025年10月1日–28日", "2025年12月29日–2026年1月4日". */
export function rangeLabel(start: string, end: string): string {
  const [from, to] = [parseDay(start), parseDay(end)];
  const thisYear = new Date().getFullYear();
  const year = (day: Date) => (day.getFullYear() === thisYear ? "" : `${day.getFullYear()}年`);
  if (start === end) return year(from) + shortDay(start);
  if (from.getFullYear() !== to.getFullYear()) return `${year(from)}${shortDay(start)}–${year(to)}${shortDay(end)}`;
  return year(from) + periodLabel(start, end);
}

/** When something happened, for a UTC timestamp: "今天 06:02", "昨天 22:15", "10月26日 06:02". */
export function whenLabel(timestamp: string | null): string {
  if (!timestamp) return "从未";
  const at = new Date(timestamp);
  const time = at.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const ago = daysAgo(new Date(at.getFullYear(), at.getMonth(), at.getDate()));
  if (ago === 0) return `今天 ${time}`;
  if (ago === 1) return `昨天 ${time}`;
  return `${at.getMonth() + 1}月${at.getDate()}日 ${time}`;
}

const UNIT: Record<Granularity, string> = { day: "天", week: "周", month: "月", year: "年" };

/** "每月", "每周": what one bar of a trend chart covers. */
export function everyLabel(granularity: Granularity): string {
  return `每${UNIT[granularity]}`;
}

/** A short label under a trend bar: "10/26" for days and weeks, "10月" (or "27年1月") for months, "2026年". */
export function axisLabel(start: string, granularity: Granularity): string {
  const day = parseDay(start);
  const [year, month] = [day.getFullYear(), day.getMonth() + 1];
  if (granularity === "year") return `${year}年`;
  if (granularity === "month") return month === 1 ? `${String(year).slice(2)}年1月` : `${month}月`;
  return `${month}/${day.getDate()}`;
}

/** The full name of a period: "2026年10月", "10月26日–11月1日", "10月28日 周三", "2025年". */
export function periodName(period: { start: string; end: string }, granularity: Granularity): string {
  const day = parseDay(period.start);
  const otherYear = day.getFullYear() !== new Date().getFullYear() ? `${day.getFullYear()}年` : "";
  if (granularity === "year") return `${day.getFullYear()}年`;
  if (granularity === "month") return `${day.getFullYear()}年${day.getMonth() + 1}月`;
  if (granularity === "week") return rangeLabel(period.start, period.end);
  return `${otherYear}${shortDay(period.start)} ${WEEKDAYS[day.getDay()]}`;
}

/** What a period is compared with, phrased to follow "比": "上月同期", "上周", "前 3 个月平均". */
export function compareLabel(compare: CompareMode, granularity: Granularity, complete: boolean): string {
  if (compare === "average") return `前 3 ${granularity === "month" ? "个月" : UNIT[granularity]}平均`;
  if (compare === "year" && granularity !== "year") return "去年同期";
  const previous = { day: "前一天", week: "上周", month: "上月", year: "去年" }[granularity];
  return complete || granularity === "day" ? previous : `${previous}同期`;
}

export function percent(fraction: number): string {
  const value = Math.abs(fraction * 100);
  if (value > 0 && value < 0.1) return "<0.1%";
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}%`;
}
