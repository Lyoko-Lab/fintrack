const MINUS = "−";
const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const wholeDollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** $1,234.56 from cents. `whole` drops the cents; `signed` adds + to positive amounts. */
export function money(cents: number | null | undefined, { whole = false, signed = false } = {}): string {
  if (cents == null) return "—";
  const text = (whole ? wholeDollars : dollars).format(Math.abs(cents) / 100);
  if (cents < 0) return MINUS + text;
  return signed && cents > 0 ? `+${text}` : text;
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

export function percent(fraction: number): string {
  const value = Math.abs(fraction * 100);
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}%`;
}
