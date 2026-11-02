import type { CardPayment } from "../api";
import { useI18n } from "../i18n";

const SOON_DAYS = 7;

/** Where a card's payment stands: "Due in 4 days", "Due today", "3 days overdue", "Paid". Spelled out, never color alone. */
export function DueState({ payment }: { payment: CardPayment }) {
  const { t } = useI18n();
  const days = payment.days_left;
  if (payment.state === "paid") {
    return (
      <span className="due-state paid">
        <span aria-hidden="true">✓ </span>
        {t.payments.paid}
      </span>
    );
  }
  if (payment.state === "overdue") {
    return (
      <span className="due-state overdue">
        <span aria-hidden="true">! </span>
        {days !== null && days < 0 ? t.payments.overdueBy(-days) : t.payments.overdue}
      </span>
    );
  }
  if (days === null) return <span className="due-state">{t.payments.dueUnknown}</span>;
  return (
    <span className={`due-state${days <= SOON_DAYS ? " soon" : ""}`}>
      {days === 0 ? t.payments.dueToday : days === 1 ? t.payments.dueTomorrow : t.payments.dueIn(days)}
    </span>
  );
}
