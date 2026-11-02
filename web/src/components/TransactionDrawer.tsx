import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Direction, type LedgerRow, type MatchField, type RuleCondition, type TransactionEdit } from "../api";
import { dayHeading, money, shortDay } from "../format";
import { useI18n, type Messages } from "../i18n";
import { invalidateLedger } from "../queries";
import { CategorySelect } from "./CategorySelect";
import { RuleFields } from "./RuleFields";
import { accountLabel } from "./TransactionList";

/** Why the automatic category was chosen (enrich.py's rule codes). */
function explain(row: LedgerRow, t: Messages): string {
  const reasons = t.drawer.reasons;
  switch (row.category_rule) {
    case "user_rule":
      return reasons.userRule(`${t.rules.match[row.user_rule_field ?? "description"]} ${row.user_rule_pattern ?? ""}`);
    case "account":
      return reasons.account;
    case "p2p":
      return row.amount_cents > 0 ? reasons.p2pIn : reasons.p2pOut;
    case "card_payment":
      return reasons.cardPayment;
    case "payroll":
      return reasons.payroll;
    case "tax_refund":
      return reasons.taxRefund;
    case "interest":
      return reasons.interest;
    case "pfc":
      return reasons.plaid(row.pfc_detailed ?? "—");
    case "direction":
      return reasons.direction(row.pfc_detailed ?? "—");
    case "pair":
      return reasons.pair(
        `${row.peer_account_name ?? reasons.otherAccount}${row.peer_account_mask ? ` ··${row.peer_account_mask}` : ""}`,
      );
    default:
      return reasons.fallback;
  }
}

/** A starting keyword from the bank's description: its first few words, minus numbers and reference codes. */
function keywordFrom(row: LedgerRow): string {
  const words = (row.description ?? row.original_description ?? "").split(/\s+/).filter((word) => word && !/\d/.test(word));
  return words.slice(0, 3).join(" ");
}

export function TransactionDrawer({ row, onClose }: { row: LedgerRow; onClose(): void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: Infinity });
  const [categoryId, setCategoryId] = useState(row.category_id ?? "");
  const [note, setNote] = useState(row.note ?? "");
  const [applyRule, setApplyRule] = useState(false);
  const [rule, setRule] = useState<RuleCondition>({
    match_field: row.merchant_name ? "merchant" : "description",
    pattern: row.merchant_name ?? keywordFrom(row),
    direction: null,
  });
  const [directionChosen, setDirectionChosen] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Refunds belong with their purchases, so spending rules default to both directions;
  // income and transfer rules default to the direction of this transaction.
  const kind = categories.data?.find((category) => category.id === categoryId)?.kind;
  const ownDirection: Direction = row.amount_cents > 0 ? "inflow" : "outflow";
  const condition: RuleCondition = directionChosen ? rule : { ...rule, direction: kind && kind !== "expense" ? ownDirection : null };
  const onRuleChange = (next: RuleCondition) => {
    if (next.direction !== condition.direction) setDirectionChosen(true);
    const suggestion = (field: MatchField) => (field === "merchant" ? (row.merchant_name ?? "") : keywordFrom(row));
    setRule(next.match_field === rule.match_field ? next : { ...next, pattern: suggestion(next.match_field) });
  };

  const changes: TransactionEdit = {};
  if (categoryId && categoryId !== row.category_id) changes.category_id = categoryId;
  if (note.trim() !== (row.note ?? "")) changes.note = note.trim() || null;
  const ruleReady = applyRule && Boolean(categoryId) && condition.pattern.trim() !== "";

  const save = useMutation({
    mutationFn: async () => {
      if (!ruleReady) {
        await api.editTransaction(row.id, changes);
        return;
      }
      await api.saveRule({ ...condition, category_id: categoryId });
      // From now on the rule decides this transaction, so a category set on it by hand gives way.
      const rest: TransactionEdit = {};
      if (row.category_edited) rest.category_id = null;
      if ("note" in changes) rest.note = changes.note;
      if (Object.keys(rest).length > 0) await api.editTransaction(row.id, rest);
    },
    onSuccess: () => {
      // A new category can move money between income, spending and transfers.
      void invalidateLedger(queryClient);
      onClose();
    },
  });
  const revert = useMutation({
    mutationFn: () => api.editTransaction(row.id, { category_id: null }),
    onSuccess: () => {
      void invalidateLedger(queryClient);
      onClose();
    },
  });

  useEffect(() => closeButton.current?.focus(), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSave = ruleReady || Object.keys(changes).length > 0;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };
  const busy = save.isPending || revert.isPending;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <h2 id="drawer-title">{row.display_name ?? t.drawer.title}</h2>
          <button ref={closeButton} type="button" className="icon-button" aria-label={t.common.close} onClick={onClose}>
            ×
          </button>
        </header>
        <p className={`drawer-amount${row.amount_cents > 0 && row.flow_type !== "transfer" ? " inflow" : ""}`}>
          {money(row.amount_cents, { signed: true })}
        </p>

        <dl className="details">
          <dt>{t.drawer.date}</dt>
          <dd>
            {dayHeading(row.transaction_date)}
            {row.posted_date !== row.transaction_date && (
              <span className="muted">{t.drawer.postedOn(shortDay(row.posted_date))}</span>
            )}
          </dd>
          <dt>{t.drawer.account}</dt>
          <dd>
            {accountLabel(row)} · {row.account_name}
          </dd>
          <dt>{t.drawer.status}</dt>
          <dd>{row.pending ? t.transactions.pending : t.drawer.posted}</dd>
          <dt>{t.drawer.bankDescription}</dt>
          <dd className="raw">{row.original_description ?? "—"}</dd>
        </dl>

        <form className="drawer-form" onSubmit={submit}>
          <label htmlFor="drawer-category">{t.drawer.category}</label>
          <CategorySelect
            id="drawer-category"
            categories={categories.data ?? []}
            value={categoryId}
            onChange={setCategoryId}
          />
          <p className="hint">{row.category_edited ? t.drawer.manual : t.drawer.automatic(explain(row, t))}</p>

          <div className="rule-option">
            <label className="checkbox">
              <input type="checkbox" checked={applyRule} onChange={(event) => setApplyRule(event.target.checked)} />
              {t.drawer.applyRule}
            </label>
            {applyRule && (
              <>
                <RuleFields value={condition} onChange={onRuleChange} />
                <p className="hint">{t.drawer.ruleHint}</p>
              </>
            )}
          </div>

          <label htmlFor="drawer-note">{t.drawer.note}</label>
          <textarea id="drawer-note" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />

          {(save.error ?? revert.error) && <p className="error">{(save.error ?? revert.error)?.message}</p>}
          <div className="drawer-actions">
            {row.category_edited ? (
              <button type="button" disabled={busy} onClick={() => revert.mutate()}>
                {t.drawer.revert}
              </button>
            ) : null}
            <button type="submit" className="primary" disabled={!canSave || busy}>
              {save.isPending ? t.common.saving : ruleReady ? t.drawer.saveWithRule : t.common.save}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
