import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type Direction, type LedgerRow, type MatchField, type RuleCondition, type TransactionEdit } from "../api";
import { dayHeading, money, shortDay } from "../format";
import { invalidateLedger } from "../queries";
import { CategorySelect } from "./CategorySelect";
import { MATCH_LABELS, RuleFields } from "./RuleFields";
import { accountLabel } from "./TransactionList";

/** Why the automatic category was chosen (enrich.py's rule codes). */
function explain(row: LedgerRow): string {
  switch (row.category_rule) {
    case "user_rule":
      return `按你的规则「${MATCH_LABELS[row.user_rule_field ?? "description"]} ${row.user_rule_pattern ?? ""}」归类。`;
    case "account":
      return "贷款、投资等非现金账户上的交易，不计入收支。";
    case "p2p":
      return row.amount_cents > 0
        ? "个人转账收入（Zelle、Venmo 等），按 AA 或报销收回处理，冲减支出。"
        : "个人转账转出（Zelle、Venmo 等），计入支出。";
    case "card_payment":
      return "识别为信用卡还款，不计入收支。";
    case "payroll":
      return "描述里有工资入账的关键词。";
    case "tax_refund":
      return "识别为退税。";
    case "interest":
      return "识别为利息收入。";
    case "pfc":
      return `依据 Plaid 的分类：${row.pfc_detailed ?? "—"}。`;
    case "direction":
      return `Plaid 的分类（${row.pfc_detailed ?? "—"}）与资金方向不符，已按方向调整。`;
    case "pair":
      return `和 ${row.peer_account_name ?? "另一个账户"}${row.peer_account_mask ? ` ··${row.peer_account_mask}` : ""} 上一笔金额相同、方向相反的交易配成了一对转账，不计入收支。`;
    default:
      return "没有可用的分类信息，按资金方向归类。";
  }
}

/** A starting keyword from the bank's description: its first few words, minus numbers and reference codes. */
function keywordFrom(row: LedgerRow): string {
  const words = (row.description ?? row.original_description ?? "").split(/\s+/).filter((word) => word && !/\d/.test(word));
  return words.slice(0, 3).join(" ");
}

export function TransactionDrawer({ row, onClose }: { row: LedgerRow; onClose(): void }) {
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
          <h2 id="drawer-title">{row.display_name ?? "交易详情"}</h2>
          <button ref={closeButton} type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>
        <p className={`drawer-amount${row.amount_cents > 0 && row.flow_type !== "transfer" ? " inflow" : ""}`}>
          {money(row.amount_cents, { signed: true })}
        </p>

        <dl className="details">
          <dt>交易日期</dt>
          <dd>
            {dayHeading(row.transaction_date)}
            {row.posted_date !== row.transaction_date && <span className="muted">（{shortDay(row.posted_date)} 入账）</span>}
          </dd>
          <dt>账户</dt>
          <dd>
            {accountLabel(row)} · {row.account_name}
          </dd>
          <dt>状态</dt>
          <dd>{row.pending ? "待入账" : "已入账"}</dd>
          <dt>银行原始描述</dt>
          <dd className="raw">{row.original_description ?? "—"}</dd>
        </dl>

        <form className="drawer-form" onSubmit={submit}>
          <label htmlFor="drawer-category">分类</label>
          <CategorySelect
            id="drawer-category"
            categories={categories.data ?? []}
            value={categoryId}
            onChange={setCategoryId}
          />
          <p className="hint">{row.category_edited ? "这是你手动设置的分类。" : `自动分类：${explain(row)}`}</p>

          <div className="rule-option">
            <label className="checkbox">
              <input type="checkbox" checked={applyRule} onChange={(event) => setApplyRule(event.target.checked)} />
              以后同样的交易也归入这个分类
            </label>
            {applyRule && (
              <>
                <RuleFields value={condition} onChange={onRuleChange} />
                <p className="hint">会新建一条规则，历史交易也会重新归类；单独改过分类的交易不受影响。</p>
              </>
            )}
          </div>

          <label htmlFor="drawer-note">备注</label>
          <textarea id="drawer-note" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />

          {(save.error ?? revert.error) && <p className="error">{(save.error ?? revert.error)?.message}</p>}
          <div className="drawer-actions">
            {row.category_edited ? (
              <button type="button" disabled={busy} onClick={() => revert.mutate()}>
                恢复自动分类
              </button>
            ) : null}
            <button type="submit" className="primary" disabled={!canSave || busy}>
              {save.isPending ? "保存中…" : ruleReady ? "保存并应用规则" : "保存"}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
