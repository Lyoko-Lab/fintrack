import type { Category } from "../api";
import { categoryName, useI18n } from "../i18n";

interface CategorySelectProps {
  categories: Category[];
  value: string;
  onChange(value: string): void;
  /** Lets the parent groups be picked too (for filtering); otherwise only leaves can be chosen. */
  allowGroups?: boolean;
  placeholder?: string;
  id?: string;
  label?: string; // accessible name when there is no visible <label>
}

/** Categories grouped under their parents, in the taxonomy's own order. */
export function CategorySelect({ categories, value, onChange, allowGroups, placeholder, id, label }: CategorySelectProps) {
  const { t } = useI18n();
  const children = (parentId: string) => categories.filter((c) => c.parent_id === parentId);
  // Transfers are categorized like everything else, but never count as income or spending.
  const kindHint = (kind: Category["kind"]) => (kind === "transfer" ? t.categorySelect.notCounted : "");
  return (
    <select id={id} aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {categories
        .filter((c) => c.parent_id === null)
        .map((top) => {
          const leaves = children(top.id);
          if (leaves.length === 0) {
            return (
              <option key={top.id} value={top.id}>
                {categoryName(top)}
                {kindHint(top.kind)}
              </option>
            );
          }
          return (
            <optgroup key={top.id} label={`${categoryName(top)}${kindHint(top.kind)}`}>
              {allowGroups && <option value={top.id}>{t.categorySelect.all(categoryName(top))}</option>}
              {leaves.map((leaf) => (
                <option key={leaf.id} value={leaf.id}>
                  {categoryName(leaf)}
                </option>
              ))}
            </optgroup>
          );
        })}
    </select>
  );
}
