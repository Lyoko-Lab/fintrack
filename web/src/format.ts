import type { CompareMode, Granularity } from "./api";
import { messages } from "./i18n";

const MINUS = "−";
const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const wholeDollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const compactDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

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

// Dates below are worded in the active language (i18n/en.ts has the words); the examples are English.

/** A calendar date ("2026-10-28") as a local Date at midnight, so it never shifts by a time zone. */
function parseDay(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function daysAgo(day: Date, now = new Date()): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today.getTime() - day.getTime()) / 86_400_000);
}

/** A date's year when it isn't this one: labels leave the current year unsaid. */
function otherYear(day: Date): number | undefined {
  return day.getFullYear() === new Date().getFullYear() ? undefined : day.getFullYear();
}

/** "Oct 28". */
export function shortDay(iso: string): string {
  const day = parseDay(iso);
  return messages().dates.day(day.getMonth(), day.getDate());
}

/** "Tue, Oct 28", or "Sat, Dec 27, 2025" in another year. */
function weekdayName(day: Date): string {
  const words = messages().dates;
  return words.withWeekday(words.day(day.getMonth(), day.getDate(), otherYear(day)), day.getDay());
}

/** Feed section heading: "Today · Tue, Oct 28", "Yesterday · Mon, Oct 27", "Sun, Oct 26". */
export function dayHeading(iso: string): string {
  const day = parseDay(iso);
  const ago = daysAgo(day);
  if (ago === 0) return messages().dates.today(weekdayName(day));
  if (ago === 1) return messages().dates.yesterday(weekdayName(day));
  return weekdayName(day);
}

/** From one day to another, with the years `yearOf` names. */
function span(start: string, end: string, yearOf: (day: Date) => number | undefined): string {
  const words = messages().dates;
  const [from, to] = [parseDay(start), parseDay(end)];
  const day = (date: Date, year?: number) => words.day(date.getMonth(), date.getDate(), year);
  if (start === end) return day(from, yearOf(from));
  if (from.getFullYear() !== to.getFullYear()) return words.span(day(from, yearOf(from)), day(to, yearOf(to)));
  if (from.getMonth() === to.getMonth()) return words.days(from.getMonth(), from.getDate(), to.getDate(), yearOf(from));
  return words.span(day(from), day(to), yearOf(from));
}

/** "Oct 1–28", or "Sep 29 – Oct 3" across months. */
export function periodLabel(start: string, end: string): string {
  return span(start, end, () => undefined);
}

/** Like periodLabel, but names years that aren't this one: "Oct 1–28, 2025", "Dec 29, 2025 – Jan 4". */
export function rangeLabel(start: string, end: string): string {
  return span(start, end, otherYear);
}

/** When something happened, for a UTC timestamp: "today at 6:02 AM", "Oct 26 at 6:02 AM"; null for never. */
export function whenLabel(timestamp: string | null): string | null {
  if (!timestamp) return null;
  const words = messages().dates;
  const at = new Date(timestamp);
  const time = words.time(at);
  const ago = daysAgo(new Date(at.getFullYear(), at.getMonth(), at.getDate()));
  if (ago === 0) return words.atToday(time);
  if (ago === 1) return words.atYesterday(time);
  return words.at(words.day(at.getMonth(), at.getDate()), time);
}

/** A short label under a trend bar: "10/26" for days and weeks, "Oct" (or "Jan ’27") for months, "2026". */
export function axisLabel(start: string, granularity: Granularity): string {
  const words = messages().dates;
  const day = parseDay(start);
  if (granularity === "year") return words.year(day.getFullYear());
  if (granularity === "month") return words.monthTick(day.getMonth(), day.getMonth() === 0 ? day.getFullYear() : undefined);
  return `${day.getMonth() + 1}/${day.getDate()}`;
}

/** The full name of a period: "October 2026", "Oct 26 – Nov 1", "Wed, Oct 28", "2025". */
export function periodName(period: { start: string; end: string }, granularity: Granularity): string {
  const words = messages().dates;
  const day = parseDay(period.start);
  if (granularity === "year") return words.year(day.getFullYear());
  if (granularity === "month") return words.month(day.getMonth(), day.getFullYear());
  if (granularity === "week") return rangeLabel(period.start, period.end);
  return weekdayName(day);
}

/** What a period is compared with, phrased to follow "than": "the same period last month", "last week". */
export function compareLabel(compare: CompareMode, granularity: Granularity, complete: boolean): string {
  const words = messages().comparison;
  if (compare === "average") return words.average[granularity];
  if (compare === "year" && granularity !== "year") return words.lastYear;
  return (complete ? words.previous : words.previousSoFar)[granularity];
}

export function percent(fraction: number): string {
  const value = Math.abs(fraction * 100);
  if (value > 0 && value < 0.1) return "<0.1%";
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}%`;
}
