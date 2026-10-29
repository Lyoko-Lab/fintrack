import { useState } from "react";
import type { LedgerRow } from "../api";
import { dayHeading, money } from "../format";

export function accountLabel(row: Pick<LedgerRow, "institution_name" | "account_name" | "account_mask">): string {
  const name = row.institution_name ?? row.account_name;
  return row.account_mask ? `${name} ··${row.account_mask}` : name;
}

function groupByDay(rows: LedgerRow[]): [string, LedgerRow[]][] {
  const groups: [string, LedgerRow[]][] = [];
  for (const row of rows) {
    const last = groups.at(-1);
    if (last && last[0] === row.transaction_date) last[1].push(row);
    else groups.push([row.transaction_date, [row]]);
  }
  return groups;
}

function Avatar({ row }: { row: LedgerRow }) {
  const [broken, setBroken] = useState(false);
  if (row.flow_type === "transfer") return <span className="avatar transfer" aria-hidden="true">⇄</span>;
  if (row.logo_url && !broken) {
    return (
      <img
        className="avatar"
        src={row.logo_url}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <span className="avatar" aria-hidden="true">
      {(row.display_name ?? "?").trim().charAt(0).toUpperCase()}
    </span>
  );
}

function TransactionRow({ row, onSelect }: { row: LedgerRow; onSelect(row: LedgerRow): void }) {
  const transfer = row.flow_type === "transfer";
  return (
    <button type="button" className={`txn-row${transfer ? " is-transfer" : ""}`} onClick={() => onSelect(row)}>
      <Avatar row={row} />
      <span className="txn-main">
        <span className="txn-name">
          <span className="txn-title">{row.display_name ?? "（无描述）"}</span>
          {row.pending ? <span className="badge pending">待入账</span> : null}
        </span>
        <span className="txn-meta">
          <span className="chip">{row.category_name ?? "未分类"}</span>
          <span>{accountLabel(row)}</span>
          {row.note && <span className="txn-note">{row.note}</span>}
        </span>
      </span>
      <span className={`txn-amount${row.amount_cents > 0 && !transfer ? " inflow" : ""}`}>
        {money(row.amount_cents, { signed: true })}
      </span>
    </button>
  );
}

export function TransactionList({ rows, onSelect }: { rows: LedgerRow[]; onSelect(row: LedgerRow): void }) {
  return (
    <div className="txn-list">
      {groupByDay(rows).map(([day, items]) => (
        <section key={day} className="txn-day">
          <h3 className="txn-day-label">{dayHeading(day)}</h3>
          <ul>
            {items.map((row) => (
              <li key={row.id}>
                <TransactionRow row={row} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
