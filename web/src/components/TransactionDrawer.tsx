import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type LedgerRow, type TransactionEdit } from "../api";
import { dayHeading, money, shortDay } from "../format";
import { CategorySelect } from "./CategorySelect";
import { accountLabel } from "./TransactionList";

/** Why the automatic category was chosen (enrich.py's rule codes). */
function explain(row: LedgerRow): string {
  switch (row.category_rule) {
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

export function TransactionDrawer({ row, onClose }: { row: LedgerRow; onClose(): void }) {
  const queryClient = useQueryClient();
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, staleTime: Infinity });
  const [categoryId, setCategoryId] = useState(row.category_id ?? "");
  const [note, setNote] = useState(row.note ?? "");
  const closeButton = useRef<HTMLButtonElement>(null);

  const save = useMutation({
    mutationFn: (changes: TransactionEdit) => api.editTransaction(row.id, changes),
    onSuccess: () => {
      // A new category can move money between income, spending and transfers.
      void queryClient.invalidateQueries({ queryKey: ["activity"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      onClose();
    },
  });

  useEffect(() => closeButton.current?.focus(), []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const changes: TransactionEdit = {};
  if (categoryId && categoryId !== row.category_id) changes.category_id = categoryId;
  if (note.trim() !== (row.note ?? "")) changes.note = note.trim() || null;
  const dirty = Object.keys(changes).length > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (dirty) save.mutate(changes);
  };

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

          <label htmlFor="drawer-note">备注</label>
          <textarea id="drawer-note" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />

          {save.error && <p className="error">{save.error.message}</p>}
          <div className="drawer-actions">
            {row.category_edited ? (
              <button type="button" disabled={save.isPending} onClick={() => save.mutate({ category_id: null })}>
                恢复自动分类
              </button>
            ) : null}
            <button type="submit" className="primary" disabled={!dirty || save.isPending}>
              {save.isPending ? "保存中…" : "保存"}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
