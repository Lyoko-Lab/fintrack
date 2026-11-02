import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Direction, type MatchField, type RuleCondition } from "../api";
import { useI18n } from "../i18n";

const MATCH_FIELDS: MatchField[] = ["merchant", "description"];
const DIRECTIONS: Direction[] = ["inflow", "outflow"];

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
  const { t } = useI18n();
  const condition = useDebounced(value);
  const ready = condition.pattern.trim() !== "";
  const preview = useQuery({
    queryKey: ["rules", "preview", condition],
    queryFn: () => api.previewRule(condition),
    enabled: ready,
  });

  let hint = t.rules.hint;
  if (ready && preview.data) {
    hint = preview.data.matches ? t.rules.matching(preview.data.matches) : t.rules.noneMatching;
  } else if (ready && preview.error) {
    hint = preview.error.message;
  }

  return (
    <div className="rule-fields">
      <div className="rule-fields-row">
        <select
          aria-label={t.rules.matchOn}
          value={value.match_field}
          onChange={(event) => onChange({ ...value, match_field: event.target.value as MatchField })}
        >
          {MATCH_FIELDS.map((field) => (
            <option key={field} value={field}>
              {t.rules.match[field]}
            </option>
          ))}
        </select>
        <input
          aria-label={value.match_field === "merchant" ? t.rules.merchant : t.rules.keyword}
          placeholder={value.match_field === "merchant" ? t.rules.merchantExample : t.rules.keywordExample}
          maxLength={100}
          value={value.pattern}
          onChange={(event) => onChange({ ...value, pattern: event.target.value })}
        />
        <select
          aria-label={t.rules.directionLabel}
          value={value.direction ?? ""}
          onChange={(event) => onChange({ ...value, direction: (event.target.value || null) as Direction | null })}
        >
          <option value="">{t.rules.eitherDirection}</option>
          {DIRECTIONS.map((direction) => (
            <option key={direction} value={direction}>
              {t.rules.direction[direction]}
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
