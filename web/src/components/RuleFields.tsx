import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Direction, type MatchField, type RuleCondition } from "../api";

export const MATCH_LABELS: Record<MatchField, string> = { merchant: "商户名称是", description: "描述包含" };
export const DIRECTION_LABELS: Record<Direction, string> = { inflow: "只限转入", outflow: "只限转出" };

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** The "if" half of a rule, with a live count of the transactions it would match. */
export function RuleFields({ value, onChange }: { value: RuleCondition; onChange(value: RuleCondition): void }) {
  const condition = useDebounced(value);
  const ready = condition.pattern.trim() !== "";
  const preview = useQuery({
    queryKey: ["rules", "preview", condition],
    queryFn: () => api.previewRule(condition),
    enabled: ready,
  });

  let hint = "填写商户名称或关键词，忽略大小写。";
  if (ready && preview.data) {
    hint = preview.data.matches ? `目前有 ${preview.data.matches} 笔交易符合这个条件。` : "目前没有交易符合这个条件。";
  } else if (ready && preview.error) {
    hint = preview.error.message;
  }

  return (
    <div className="rule-fields">
      <div className="rule-fields-row">
        <select
          aria-label="匹配方式"
          value={value.match_field}
          onChange={(event) => onChange({ ...value, match_field: event.target.value as MatchField })}
        >
          {(Object.keys(MATCH_LABELS) as MatchField[]).map((field) => (
            <option key={field} value={field}>
              {MATCH_LABELS[field]}
            </option>
          ))}
        </select>
        <input
          aria-label={value.match_field === "merchant" ? "商户名称" : "关键词"}
          placeholder={value.match_field === "merchant" ? "例如 Starbucks" : "例如 PAYROLL"}
          maxLength={100}
          value={value.pattern}
          onChange={(event) => onChange({ ...value, pattern: event.target.value })}
        />
        <select
          aria-label="适用方向"
          value={value.direction ?? ""}
          onChange={(event) => onChange({ ...value, direction: (event.target.value || null) as Direction | null })}
        >
          <option value="">转入和转出都适用</option>
          {(Object.keys(DIRECTION_LABELS) as Direction[]).map((direction) => (
            <option key={direction} value={direction}>
              {DIRECTION_LABELS[direction]}
            </option>
          ))}
        </select>
      </div>
      <p className="hint" aria-live="polite">
        {hint}
      </p>
    </div>
  );
}
