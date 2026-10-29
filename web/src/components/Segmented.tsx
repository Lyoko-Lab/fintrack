interface SegmentedProps<T extends string> {
  label: string; // accessible name of the group
  options: { value: T; label: string }[];
  value: T;
  onChange(value: T): void;
}

/** A row of mutually exclusive toggle buttons, for switches with only a few choices. */
export function Segmented<T extends string>({ label, options, value, onChange }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button key={option.value} type="button" aria-pressed={option.value === value} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
