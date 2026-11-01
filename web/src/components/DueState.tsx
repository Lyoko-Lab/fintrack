import type { CardPayment } from "../api";

const SOON_DAYS = 7;

/** Where a card's payment stands: "还有 4 天", "今天到期", "已逾期 3 天", "已还清". Spelled out, never color alone. */
export function DueState({ payment }: { payment: CardPayment }) {
  const days = payment.days_left;
  if (payment.state === "paid") {
    return (
      <span className="due-state paid">
        <span aria-hidden="true">✓ </span>已还清
      </span>
    );
  }
  if (payment.state === "overdue") {
    return (
      <span className="due-state overdue">
        <span aria-hidden="true">! </span>
        {days !== null && days < 0 ? `已逾期 ${-days} 天` : "已逾期"}
      </span>
    );
  }
  if (days === null) return <span className="due-state">还款日未知</span>;
  return (
    <span className={`due-state${days <= SOON_DAYS ? " soon" : ""}`}>
      {days === 0 ? "今天到期" : days === 1 ? "明天到期" : `还有 ${days} 天`}
    </span>
  );
}
