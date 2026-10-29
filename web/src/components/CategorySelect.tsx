import type { Category } from "../api";

const KIND_HINT: Record<Category["kind"], string> = { expense: "", income: "", transfer: "（不计入收支）" };

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
  const children = (parentId: string) => categories.filter((c) => c.parent_id === parentId);
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
                {top.name}
                {KIND_HINT[top.kind]}
              </option>
            );
          }
          return (
            <optgroup key={top.id} label={`${top.name}${KIND_HINT[top.kind]}`}>
              {allowGroups && <option value={top.id}>全部{top.name}</option>}
              {leaves.map((leaf) => (
                <option key={leaf.id} value={leaf.id}>
                  {leaf.name}
                </option>
              ))}
            </optgroup>
          );
        })}
    </select>
  );
}
